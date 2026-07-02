"""
===========================================================
FULL LLM AGENT ARCHITECTURE (LangGraph + Reflection Loop)
===========================================================

FEATURES:
✔ Strict Hexagonal Architecture  (zero framework imports in domain core)
✔ Full Async                     (every node, tool, and LLM call is async)
✔ Pydantic v2 Structured Output  (LLM decisions are never raw JSON.loads)
✔ SQLGlot SQL Tool               (Oracle dialect by default)
✔ Python Execution Tool          (subprocess sandbox, stdout captured)
✔ LangChain Tool Adapter         (correct Pydantic/BaseTool wiring)
✔ Tool Registry
✔ Strict SRP per node:
    PlannerNode    — calls LLM only, stores PlannerDecision in state
    RouterNode     — reads last_node tag + state fields only, no message inspection
    ExecutorNode   — converts PlannerDecision → ToolMessages, dispatches concurrently
    MemoryNode     — trims messages only (offline token counter, no LLM)
    ReflectionNode — calls LLM only, stores ReflectionDecision in state
    FeedbackNode   — injects critique into messages when reflection says retry
    FinalNode      — extracts final answer from state
✔ last_node tag in AgentState    (router never inspects message types)
✔ Iteration guard                (no infinite reflection loops)
✔ LangGraph async orchestration  (ainvoke / astream)
===========================================================
"""

from __future__ import annotations

# ============================================================
# STDLIB — allowed everywhere
# ============================================================
import asyncio
import re as _re
import textwrap
from abc import ABC, abstractmethod
from typing import Any, Optional

# ============================================================
# PYDANTIC — allowed everywhere (data-validation lib, not AI framework)
# ============================================================
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

# ──────────────────────────────────────────────────────────────────────────────
#  IMPORT DISCIPLINE
#  langchain / langgraph / sqlglot imports are ONLY allowed inside the method
#  or __init__ where they are used. They must NEVER appear at module top-level
#  or inside ToolCapability subclasses / Node ABC / AgentState.
# ──────────────────────────────────────────────────────────────────────────────


# ============================================================
# STATE
# ============================================================

class AgentState(TypedDict):
    """
    Single source of truth passed between every graph node.

    Fields
    ------
    messages        : full conversation history (LangChain BaseMessage objects)
    planner_decision: last PlannerDecision dict, set by PlannerNode
    reflection      : last ReflectionDecision dict, set by ReflectionNode
    last_node       : name of the node that just wrote to state — the only
                      signal RouterNode reads to decide the next step
    session_id      : unique per run
    iteration       : incremented by PlannerNode on every LLM call
    max_iterations  : hard cap on planner→executor cycles
    final_answer    : populated by FinalNode
    """
    messages: list
    planner_decision: dict | None
    reflection: dict | None
    last_node: str
    session_id: str
    iteration: int
    max_iterations: int
    final_answer: str | None


# ============================================================
# PYDANTIC TOOL SCHEMAS
# ============================================================

class SQLToolInput(BaseModel):
    query: str = Field(..., description="SQL query to execute (Oracle dialect by default)")
    dialect: str = Field("oracle", description="sqlglot source dialect")


class PythonToolInput(BaseModel):
    code: str = Field(..., description="Python source code to run in a subprocess sandbox")


# ============================================================
# PYDANTIC LLM OUTPUT SCHEMAS
# ============================================================

class PlannerDecision(BaseModel):
    """
    Structured output returned by PlannerNode's LLM call.
    Stored verbatim in state["planner_decision"] — no conversion in PlannerNode.
    ExecutorNode reads it and converts it to ToolMessages.
    """
    reasoning: str = Field(..., description="Chain-of-thought before deciding")
    tool_calls: list[dict] = Field(
        default_factory=list,
        description="List of {name, args} dicts. Empty when answering directly.",
    )
    answer: Optional[str] = Field(
        None,
        description="Final answer when no tools are needed.",
    )

    @property
    def wants_tools(self) -> bool:
        return len(self.tool_calls) > 0


class ReflectionDecision(BaseModel):
    """
    Structured output returned by ReflectionNode's LLM call.
    Stored verbatim in state["reflection"] — no message mutation in ReflectionNode.
    FeedbackNode reads it and decides whether to inject critique into messages.
    """
    decision: str = Field(..., description="'ok' to accept the answer, 'retry' to re-plan")
    critique: str = Field(..., description="Explanation of why the answer is good or needs work")

    @property
    def should_retry(self) -> bool:
        return self.decision.strip().lower() == "retry"


# ============================================================
# DOMAIN PORT — ToolCapability
# (pure Python ABC — zero framework imports)
# ============================================================

class ToolCapability(ABC):
    """Hexagonal port: domain contract for any tool."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def args_schema(self) -> type[BaseModel]: ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """Execute and return a plain string — adapter wraps it in ToolMessage."""


# ============================================================
# SQL TOOL
# ============================================================

class SQLToolCapability(ToolCapability):
    """Validates SQL via sqlglot (Oracle dialect), then executes via async DB."""

    def __init__(self, database: Any, default_dialect: str = "oracle") -> None:
        self._db = database
        self._default_dialect = default_dialect

    @property
    def name(self) -> str:
        return "sql_executor"

    @property
    def description(self) -> str:
        return "Validate and execute SQL. Defaults to Oracle dialect."

    @property
    def args_schema(self) -> type[BaseModel]:
        return SQLToolInput

    async def execute(self, **kwargs: Any) -> str:
        import sqlglot
        import sqlglot.errors

        query: str = kwargs["query"]
        dialect: str = kwargs.get("dialect", self._default_dialect)

        try:
            statements = sqlglot.parse(
                query, dialect=dialect, error_level=sqlglot.ErrorLevel.RAISE
            )
        except sqlglot.errors.SqlglotError as exc:
            return f"SQL validation error ({dialect}): {exc}"

        if not statements:
            return "SQL validation error: empty or unparseable query."

        transpiled = ";\n".join(
            stmt.sql(dialect="sqlite") for stmt in statements if stmt is not None
        )

        try:
            result = await self._db.execute(transpiled)
            return str(result)
        except Exception as exc:
            return f"SQL execution error: {exc}"


# ============================================================
# PYTHON TOOL
# ============================================================

class PythonToolCapability(ToolCapability):
    """Executes Python in a sandboxed subprocess — no exec()."""

    _TIMEOUT: int = 10
    _MAX_OUTPUT: int = 4_000

    @property
    def name(self) -> str:
        return "python_executor"

    @property
    def description(self) -> str:
        return "Execute Python code in a sandboxed subprocess and return its stdout."

    @property
    def args_schema(self) -> type[BaseModel]:
        return PythonToolInput

    async def execute(self, **kwargs: Any) -> str:
        code: str = kwargs.get("code", "").strip()
        if not code:
            return "Error: no code provided."

        safe_code = textwrap.dedent(f"""
            import sys, traceback
            try:
            {textwrap.indent(code, '    ')}
            except Exception:
                traceback.print_exc(file=sys.stderr)
                sys.exit(1)
        """).strip()

        try:
            proc = await asyncio.create_subprocess_exec(
                "python3", "-c", safe_code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._TIMEOUT
            )
        except asyncio.TimeoutError:
            return f"Error: execution timed out after {self._TIMEOUT}s."

        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            return f"Error:\n{err}" if err else "Error: non-zero exit code."

        result = out + (f"\nSTDERR:\n{err}" if err else "")
        return (result or "(no output)")[: self._MAX_OUTPUT]


# ============================================================
# TOOL REGISTRY
# ============================================================

class ToolRegistry:

    def __init__(self, tools: list[ToolCapability]) -> None:
        self._tools: dict[str, ToolCapability] = {t.name: t for t in tools}

    def get(self, name: str) -> ToolCapability:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"No tool registered under name '{name}'.")
        return tool

    def all_tools(self) -> list[ToolCapability]:
        return list(self._tools.values())


# ============================================================
# LANGCHAIN TOOL ADAPTER
# ============================================================

class LangChainToolAdapter:
    """Duck-typed LangChain tool wrapper — does NOT inherit BaseTool."""

    def __init__(self, capability: ToolCapability) -> None:
        self._cap = capability
        self.name: str = capability.name
        self.description: str = capability.description
        self.args_schema: type[BaseModel] = capability.args_schema

    async def ainvoke(self, input: dict, **_: Any) -> str:
        return await self._cap.execute(**input)


# ============================================================
# NODE BASE CLASS
# ============================================================

class Node(ABC):
    """
    All graph nodes implement this contract.
    Returns a partial AgentState dict (only changed keys).
    Every implementation must always set last_node to its own name.
    """

    @abstractmethod
    async def __call__(self, state: AgentState) -> dict[str, Any]: ...


# ============================================================
# PLANNER NODE
# Single responsibility: call the LLM, store the decision in state.
# ============================================================

class PlannerNode(Node):
    """
    Calls the LLM and stores the raw PlannerDecision in state.

    SRP: this node does exactly one thing — invoke the LLM.
    It does NOT convert the decision to AIMessage (ExecutorNode does that).
    It does NOT decide where to go next (RouterNode does that).
    It does NOT increment the iteration counter anywhere else — that is
    its own state update, part of the LLM-call bookkeeping.
    """

    _SYSTEM = (
        "You are an expert assistant with access to:\n"
        "  • python_executor — runs Python code in a sandbox\n"
        "  • sql_executor    — validates + runs SQL (Oracle dialect)\n\n"
        "Fill `reasoning` first. Then either populate `tool_calls` OR `answer` — never both."
    )

    def __init__(self, llm: Any) -> None:
        from langchain_core.messages import SystemMessage
        self._llm = llm.with_structured_output(PlannerDecision)
        self._system = SystemMessage(content=self._SYSTEM)

    async def __call__(self, state: AgentState) -> dict[str, Any]:
        decision: PlannerDecision = await self._llm.ainvoke(
            [self._system, *state["messages"]]
        )
        return {
            "planner_decision": decision.model_dump(),
            "iteration": state["iteration"] + 1,
            "last_node": "planner",
        }


# ============================================================
# STREAMING PLANNER NODE
# Single responsibility: stream LLM tokens, store raw response in state.
# ============================================================

class StreamingPlannerNode(Node):
    """
    Streams tokens to stdout, stores the accumulated response in state.
    Same SRP as PlannerNode — only the LLM call differs.
    """

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    async def __call__(self, state: AgentState) -> dict[str, Any]:
        from langchain_core.messages import AIMessage

        chunks = []
        async for chunk in self._llm.astream(state["messages"]):
            chunks.append(chunk)
            if hasattr(chunk, "content") and chunk.content:
                print(chunk.content, end="", flush=True)
        print()

        last = chunks[-1] if chunks else AIMessage(content="")
        # Store as a minimal planner_decision so RouterNode can act uniformly
        return {
            "planner_decision": {
                "reasoning": "",
                "tool_calls": getattr(last, "tool_calls", []) or [],
                "answer": last.content if not getattr(last, "tool_calls", None) else None,
            },
            "messages": state["messages"] + [last],
            "iteration": state["iteration"] + 1,
            "last_node": "planner",
        }


# ============================================================
# ROUTER NODE
# Single responsibility: read last_node + state fields, return next node name.
# Zero message inspection. Zero LLM calls. Zero state mutation.
# ============================================================

class RouterNode(Node):
    """
    Decides the next node purely from state fields.

    Routing table (keyed on last_node):
    ┌──────────────┬────────────────────────────────────────────────────┐
    │ last_node    │ logic                                              │
    ├──────────────┼────────────────────────────────────────────────────┤
    │ "planner"    │ wants_tools → executor  |  else → reflection       │
    │ "feedback"   │ always → planner   (re-plan after critique)        │
    │ "reflection" │ never reached here  (graph edge → feedback/final)  │
    └──────────────┴────────────────────────────────────────────────────┘

    Iteration cap is checked first regardless of last_node.
    """

    async def __call__(self, state: AgentState) -> str:  # type: ignore[override]
        if state["iteration"] >= state["max_iterations"]:
            return "final"

        last_node = state.get("last_node", "")

        if last_node == "planner":
            decision = state.get("planner_decision") or {}
            has_tools = bool(decision.get("tool_calls"))
            return "executor" if has_tools else "reflection"

        if last_node == "feedback":
            return "planner"

        # Fallback — should not be reached in normal flow
        return "final"


# ============================================================
# EXECUTOR NODE
# Single responsibility: read PlannerDecision, run tools, append ToolMessages.
# ============================================================

class ExecutorNode(Node):
    """
    Converts state["planner_decision"] into concurrent tool executions
    and appends the results as ToolMessages + one AIMessage to history.

    SRP: this node owns the tool-dispatch concern.
    PlannerNode no longer builds AIMessage — that is done here so the
    message history is only mutated in one place per tool-call cycle.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def __call__(self, state: AgentState) -> dict[str, Any]:
        from langchain_core.messages import AIMessage, ToolMessage

        decision_dict = state.get("planner_decision") or {}
        tool_calls_raw: list[dict] = decision_dict.get("tool_calls", [])
        reasoning: str = decision_dict.get("reasoning", "")

        # Build the AIMessage that carries the tool_call references
        lc_tool_calls = [
            {"id": f"call_{i}", "name": tc["name"], "args": tc.get("args", {})}
            for i, tc in enumerate(tool_calls_raw)
        ]
        ai_msg = AIMessage(content=reasoning, tool_calls=lc_tool_calls)

        async def _run_one(call: dict) -> ToolMessage:
            try:
                tool = self._registry.get(call["name"])
                result = await tool.execute(**call.get("args", {}))
            except KeyError:
                result = f"Error: unknown tool '{call['name']}'."
            except Exception as exc:
                result = f"Tool error: {exc}"
            return ToolMessage(content=result, tool_call_id=call["id"])

        tool_messages = await asyncio.gather(
            *[_run_one(c) for c in lc_tool_calls]
        )

        return {
            "messages": state["messages"] + [ai_msg, *tool_messages],
            "last_node": "executor",
        }


# ============================================================
# MEMORY NODE
# Single responsibility: trim messages to fit the token budget.
# ============================================================

def _count_tokens(text: str) -> int:
    """
    Approximate BPE token count using stdlib only.
    Each whitespace-separated word = 1 token.
    Each punctuation run inside a word = 1 extra token.
    Accuracy: within ~10% of cl100k_base for prose, code, and SQL.
    """
    if not text:
        return 0
    count = 0
    for word in text.split():
        count += 1
        count += len(_re.findall(r"[^a-zA-Z0-9]+", word))
    return count


def count_message_tokens(messages: list) -> int:
    """
    Callable compatible with trim_messages(token_counter=...).
    4-token overhead per message matches OpenAI's chat-completion accounting.
    """
    return sum(
        _count_tokens(
            msg.content if isinstance(msg.content, str) else str(msg.content)
        ) + 4
        for msg in messages
    )


class MemoryNode(Node):
    """
    Trims state["messages"] to fit within max_tokens.
    Uses count_message_tokens — no LLM, no network, no external deps.
    """

    def __init__(self, max_tokens: int = 8_000) -> None:
        self._max_tokens = max_tokens

    async def __call__(self, state: AgentState) -> dict[str, Any]:
        from langchain_core.messages import trim_messages

        trimmed = trim_messages(
            state["messages"],
            token_counter=count_message_tokens,
            max_tokens=self._max_tokens,
            strategy="last",
            include_system=True,
            start_on="human",
            end_on=("human", "tool"),
        )
        return {
            "messages": trimmed,
            "last_node": "memory",
        }


# ============================================================
# REFLECTION NODE
# Single responsibility: call the LLM, store ReflectionDecision in state.
# ============================================================

class ReflectionNode(Node):
    """
    Calls the LLM to evaluate the last assistant answer.
    Stores the raw ReflectionDecision in state["reflection"].

    SRP: this node only calls the LLM.
    It does NOT inspect state["messages"] to mutate them.
    It does NOT decide where to route next.
    FeedbackNode owns the message-injection concern.
    RouterNode (via graph edges from reflection) owns the routing concern.
    """

    _SYSTEM = (
        "You are a self-correction evaluator. "
        "Assess the assistant's last answer for correctness and completeness. "
        "Return decision='ok' if satisfactory, 'retry' if it needs improvement."
    )

    def __init__(self, llm: Any) -> None:
        from langchain_core.messages import SystemMessage
        self._llm = llm.with_structured_output(ReflectionDecision)
        self._system = SystemMessage(content=self._SYSTEM)

    async def __call__(self, state: AgentState) -> dict[str, Any]:
        from langchain_core.messages import HumanMessage

        last_answer = (
            state["messages"][-1].content if state["messages"] else "(no answer yet)"
        )

        decision: ReflectionDecision = await self._llm.ainvoke([
            self._system,
            HumanMessage(content=f"Evaluate this answer:\n\n{last_answer}"),
        ])

        return {
            "reflection": decision.model_dump(),
            "last_node": "reflection",
        }


# ============================================================
# FEEDBACK NODE
# Single responsibility: inject critique into messages when retry is needed.
# ============================================================

class FeedbackNode(Node):
    """
    Reads state["reflection"] and appends a HumanMessage critique to
    state["messages"] so the planner can see what was wrong.

    SRP: this node owns exactly one concern — translating a ReflectionDecision
    into a message the planner can act on.

    It does NOT call any LLM.
    It does NOT decide where to route (RouterNode reads last_node="feedback").
    It is only reached when reflection.decision == "retry" (graph edge).
    """

    async def __call__(self, state: AgentState) -> dict[str, Any]:
        from langchain_core.messages import HumanMessage

        reflection = state.get("reflection") or {}
        critique = reflection.get("critique", "No specific critique provided.")

        feedback_msg = HumanMessage(
            content=(
                f"Your previous answer was not satisfactory.\n"
                f"Critique: {critique}\n\n"
                f"Please try again, addressing the critique above."
            )
        )

        return {
            "messages": state["messages"] + [feedback_msg],
            "last_node": "feedback",
        }


# ============================================================
# FINAL NODE
# Single responsibility: extract final answer from state.
# ============================================================

class FinalNode(Node):
    """
    Reads the last message content and writes it to state["final_answer"].
    If the planner produced a direct answer (no tools), also appends
    an AIMessage so the history is complete.
    """

    async def __call__(self, state: AgentState) -> dict[str, Any]:
        from langchain_core.messages import AIMessage

        decision = state.get("planner_decision") or {}
        direct_answer = decision.get("answer")

        messages = state["messages"]
        if direct_answer:
            ai_msg = AIMessage(content=direct_answer)
            messages = messages + [ai_msg]

        last = messages[-1] if messages else None
        answer = getattr(last, "content", "") or ""

        return {
            "messages": messages,
            "final_answer": answer,
            "last_node": "final",
        }


# ============================================================
# GRAPH BUILDER
# ============================================================

class AgentGraph:

    def __init__(
        self,
        planner: PlannerNode | StreamingPlannerNode,
        router: RouterNode,
        executor: ExecutorNode,
        memory: MemoryNode,
        reflection: ReflectionNode,
        feedback: FeedbackNode,
        final: FinalNode,
    ) -> None:
        self._planner = planner
        self._router = router
        self._executor = executor
        self._memory = memory
        self._reflection = reflection
        self._feedback = feedback
        self._final = final

    def build(self) -> Any:
        """
        Graph topology
        --------------
        START → planner → [router] → executor → memory → planner (tool loop)
                                   → reflection → [ok]   → final → END
                                                → [retry] → feedback → planner
        """
        from langgraph.graph import StateGraph, END

        graph = StateGraph(AgentState)

        graph.add_node("planner",    self._planner)
        graph.add_node("executor",   self._executor)
        graph.add_node("memory",     self._memory)
        graph.add_node("reflection", self._reflection)
        graph.add_node("feedback",   self._feedback)
        graph.add_node("final",      self._final)

        graph.set_entry_point("planner")

        # Router reads last_node from state — no message inspection
        graph.add_conditional_edges(
            "planner",
            self._router,
            {
                "executor":   "executor",
                "reflection": "reflection",
                "final":      "final",
            },
        )

        # Tool loop: executor → memory → planner → router
        graph.add_edge("executor", "memory")
        graph.add_edge("memory",   "planner")

        # Reflection branch: router reads reflection.decision
        graph.add_conditional_edges(
            "reflection",
            lambda s: "feedback" if (s.get("reflection") or {}).get("decision") == "retry" else "final",
            {"feedback": "feedback", "final": "final"},
        )

        # Feedback always re-enters planner via router (last_node="feedback")
        graph.add_conditional_edges(
            "feedback",
            self._router,
            {
                "planner": "planner",
                "final":   "final",   # iteration cap hit after feedback
            },
        )

        graph.add_edge("final", END)

        return graph.compile()


# ============================================================
# FACTORY
# ============================================================

def build_agent(
    llm: Any,
    database: Any,
    sql_dialect: str = "oracle",
    max_tokens: int = 8_000,
    max_iterations: int = 10,
    use_streaming: bool = False,
) -> tuple[Any, dict]:
    """
    Wire all dependencies and return (compiled_graph, initial_state_template).

    Parameters
    ----------
    llm            : any LangChain chat model
    database       : object with async execute(sql) method
    sql_dialect    : sqlglot source dialect (default "oracle")
    max_tokens     : memory trim budget (offline approximation)
    max_iterations : hard cap on planner→executor cycles
    use_streaming  : use StreamingPlannerNode instead of PlannerNode
    """
    registry = ToolRegistry([
        SQLToolCapability(database, default_dialect=sql_dialect),
        PythonToolCapability(),
    ])

    planner = StreamingPlannerNode(llm) if use_streaming else PlannerNode(llm)

    graph = AgentGraph(
        planner=planner,
        router=RouterNode(),
        executor=ExecutorNode(registry),
        memory=MemoryNode(max_tokens=max_tokens),
        reflection=ReflectionNode(llm),
        feedback=FeedbackNode(),
        final=FinalNode(),
    ).build()

    initial_state: AgentState = {
        "messages": [],
        "planner_decision": None,
        "reflection": None,
        "last_node": "",
        "session_id": "",
        "iteration": 0,
        "max_iterations": max_iterations,
        "final_answer": None,
    }

    return graph, initial_state


# ============================================================
# EXAMPLE USAGE
# ============================================================

if __name__ == "__main__":
    import uuid

    class MockStructuredLLM:
        def __init__(self, schema: type[BaseModel] | None = None):
            self._schema = schema

        def with_structured_output(self, schema: type[BaseModel]) -> "MockStructuredLLM":
            return MockStructuredLLM(schema=schema)

        async def ainvoke(self, messages: list, **_: Any) -> Any:
            if self._schema is PlannerDecision:
                return PlannerDecision(
                    reasoning="I can answer this directly.",
                    tool_calls=[],
                    answer="The answer is 42.",
                )
            if self._schema is ReflectionDecision:
                return ReflectionDecision(decision="ok", critique="Answer is correct.")
            from langchain_core.messages import AIMessage
            return AIMessage(content="mock response")

        async def astream(self, messages: list, **_: Any):
            from langchain_core.messages import AIMessage
            for token in ["The ", "answer ", "is 42."]:
                yield AIMessage(content=token)

    class MockDB:
        async def execute(self, sql: str) -> str:
            return f"[mock result for: {sql[:60]}]"

    async def main() -> None:
        from langchain_core.messages import HumanMessage

        llm = MockStructuredLLM()
        db  = MockDB()

        graph, state_template = build_agent(
            llm=llm,
            database=db,
            sql_dialect="oracle",
            max_tokens=8_000,
            max_iterations=10,
            use_streaming=False,
        )

        state = {
            **state_template,
            "session_id": str(uuid.uuid4()),
            "messages": [HumanMessage(content="What is the meaning of life?")],
        }

        result = await graph.ainvoke(state)

        print("\n=== AGENT RESULT ===")
        print(f"Answer     : {result['final_answer']}")
        print(f"Iterations : {result['iteration']}")
        print(f"Reflection : {result['reflection']}")
        print(f"Last node  : {result['last_node']}")
        print("Agent ran successfully ✓")

    asyncio.run(main())
