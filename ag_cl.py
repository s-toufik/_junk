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
✔ Planner Node  (sync + streaming variants)
✔ Router        (is a proper Node subclass)
✔ Executor Node (concurrent async tool dispatch)
✔ Memory Node   (async trim_messages)
✔ Reflection Node  (structured output, no history pollution)
✔ Final Node
✔ Iteration guard (no infinite reflection loops)
✔ LangGraph async orchestration  (ainvoke / astream)
===========================================================
"""

from __future__ import annotations

# ============================================================
# STDLIB — allowed everywhere
# ============================================================
import asyncio
import textwrap
from abc import ABC, abstractmethod
from typing import Any, Optional

# ============================================================
# PYDANTIC — allowed everywhere (it is a data-validation lib,
# not an AI framework)
# ============================================================
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

# ──────────────────────────────────────────────────────────────────────────────
#  NOTE ON IMPORT DISCIPLINE
#  The rule: langchain / langgraph / sqlglot imports are ONLY allowed in:
#    • The adapter classes (LangChainToolAdapter, node implementations)
#    • The graph builder (AgentGraph)
#  They must NEVER appear in:
#    • ToolCapability and its subclasses  (domain core)
#    • Node ABC
#    • AgentState TypedDict
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
    reflection      : last ReflectionDecision, or None before first reflection
    session_id      : unique per run — useful for logging / checkpointing
    iteration       : how many planner→executor cycles have completed
    max_iterations  : hard cap — prevents infinite reflection retry loops
    final_answer    : populated by FinalNode; declared here so LangGraph
                      keeps it in state (a key not declared is silently dropped)
    """
    messages: list          # list[BaseMessage] — kept untyped to avoid import
    reflection: dict | None
    session_id: str
    iteration: int
    max_iterations: int
    final_answer: str | None


# ============================================================
# PYDANTIC TOOL SCHEMAS  (pure Pydantic — no framework imports)
# ============================================================

class SQLToolInput(BaseModel):
    query: str = Field(..., description="SQL query to execute (Oracle dialect by default)")
    dialect: str = Field("oracle", description="sqlglot source dialect")


class PythonToolInput(BaseModel):
    code: str = Field(..., description="Python source code to run in a subprocess sandbox")


# ============================================================
# PYDANTIC LLM OUTPUT SCHEMAS  (used by structured_output)
# ============================================================

class ReflectionDecision(BaseModel):
    decision: str = Field(..., description="'ok' to accept the answer, 'retry' to re-plan")
    critique: str = Field(..., description="Explanation of why the answer is good or needs work")

    @property
    def should_retry(self) -> bool:
        return self.decision.strip().lower() == "retry"


class PlannerDecision(BaseModel):
    """
    Structured output for the planner LLM.
    The LLM either produces tool_calls or a final answer — never both.
    """
    reasoning: str = Field(..., description="Chain-of-thought before deciding")
    tool_calls: list[dict] = Field(
        default_factory=list,
        description="List of {name, args} dicts for tools to invoke. Empty when answering directly.",
    )
    answer: Optional[str] = Field(
        None,
        description="Final answer when no tools are needed.",
    )

    @property
    def wants_tools(self) -> bool:
        return len(self.tool_calls) > 0


# ============================================================
# DOMAIN PORT — ToolCapability
# (pure Python ABC — zero framework imports)
# ============================================================

class ToolCapability(ABC):
    """
    Hexagonal port: the domain's contract for any tool.
    Concrete implementations know nothing about LangChain.
    """

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
        """
        All tools are async. Return a plain string result
        so the adapter layer can wrap it in a ToolMessage.
        """


# ============================================================
# SQL TOOL  (adapter — sqlglot import confined here)
# ============================================================

class SQLToolCapability(ToolCapability):
    """
    Validates SQL via sqlglot (Oracle dialect by default),
    then delegates execution to the injected async database.
    """

    def __init__(self, database: Any, default_dialect: str = "oracle") -> None:
        self._db = database
        self._default_dialect = default_dialect

    @property
    def name(self) -> str:
        return "sql_executor"

    @property
    def description(self) -> str:
        return (
            "Validate and execute a SQL query. "
            "Defaults to Oracle dialect. "
            "Pass dialect='sqlite' etc. to override."
        )

    @property
    def args_schema(self) -> type[BaseModel]:
        return SQLToolInput

    async def execute(self, **kwargs: Any) -> str:
        # sqlglot import confined to this adapter method
        import sqlglot
        import sqlglot.errors

        query: str = kwargs["query"]
        dialect: str = kwargs.get("dialect", self._default_dialect)

        # ── 1. Parse & validate in source dialect ────────────────────────────
        try:
            statements = sqlglot.parse(
                query,
                dialect=dialect,
                error_level=sqlglot.ErrorLevel.RAISE,
            )
        except sqlglot.errors.SqlglotError as exc:
            return f"SQL validation error ({dialect}): {exc}"

        if not statements:
            return "SQL validation error: empty or unparseable query."

        # ── 2. Transpile to execution dialect (sqlite for dev/test) ──────────
        transpiled = ";\n".join(
            stmt.sql(dialect="sqlite")
            for stmt in statements
            if stmt is not None
        )

        # ── 3. Execute via injected async database ───────────────────────────
        try:
            result = await self._db.execute(transpiled)
            return str(result)
        except Exception as exc:
            return f"SQL execution error: {exc}"


# ============================================================
# PYTHON TOOL  (subprocess sandbox — no exec())
# ============================================================

class PythonToolCapability(ToolCapability):
    """
    Executes Python code in an isolated subprocess.
    Captures stdout; returns stderr on non-zero exit.
    exec() is intentionally NOT used.
    """

    _TIMEOUT: int = 10          # seconds
    _MAX_OUTPUT: int = 4_000    # characters

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

        # Wrap user code so runtime errors appear in stderr cleanly
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

    def langchain_tools(self) -> list:
        """Return LangChain-compatible wrappers for all registered tools."""
        return [LangChainToolAdapter(t) for t in self._tools.values()]

    def all_tools(self) -> list[ToolCapability]:
        return list(self._tools.values())


# ============================================================
# LANGCHAIN TOOL ADAPTER
# (LangChain import confined here — correct Pydantic wiring)
# ============================================================

class LangChainToolAdapter:
    """
    Wraps a ToolCapability as a LangChain-compatible tool.

    We do NOT inherit BaseTool because BaseTool is a Pydantic BaseModel
    and would reject a raw ToolCapability in its field validators.
    Instead we expose the duck-typed interface LangGraph's ToolNode
    expects: .name, .description, .args_schema, and async ainvoke().
    """

    def __init__(self, capability: ToolCapability) -> None:
        self._cap = capability
        # Expose attributes LangGraph ToolNode reads
        self.name: str = capability.name
        self.description: str = capability.description
        self.args_schema: type[BaseModel] = capability.args_schema

    async def ainvoke(self, input: dict, **_: Any) -> str:
        return await self._cap.execute(**input)

    def invoke(self, input: dict, **_: Any) -> str:
        # Sync shim for compatibility — runs the coroutine in the current loop
        return asyncio.get_event_loop().run_until_complete(self._cap.execute(**input))


# ============================================================
# NODE BASE CLASS  (pure Python ABC)
# ============================================================

class Node(ABC):
    """
    All graph nodes implement this contract.
    Every node is async — it must not block the event loop.
    Returns a partial AgentState dict (only keys that changed).
    """

    @abstractmethod
    async def __call__(self, state: AgentState) -> dict[str, Any]: ...


# ============================================================
# PLANNER NODE  (sync LLM call, structured output)
# ============================================================

class PlannerNode(Node):
    """
    Asks the LLM what to do next via structured output.
    The LLM returns a PlannerDecision — either tool calls or a final answer.
    Uses LangChain structured output so there is NO manual JSON parsing.
    """

    _SYSTEM = (
        "You are an expert assistant. You have access to:\n"
        "  • python_executor — runs Python code in a sandbox\n"
        "  • sql_executor    — validates + runs SQL (Oracle dialect)\n\n"
        "Decide: call a tool, or answer directly. "
        "Always fill `reasoning` first. "
        "Never produce both tool_calls and answer simultaneously."
    )

    def __init__(self, llm: Any) -> None:
        # langchain import confined to adapter usage in __init__
        from langchain_core.messages import SystemMessage
        self._llm = llm.with_structured_output(PlannerDecision)
        self._system = SystemMessage(content=self._SYSTEM)

    async def __call__(self, state: AgentState) -> dict[str, Any]:
        messages = [self._system, *state["messages"]]
        decision: PlannerDecision = await self._llm.ainvoke(messages)

        # Convert structured decision → AIMessage with optional tool_calls
        from langchain_core.messages import AIMessage
        if decision.wants_tools:
            ai_msg = AIMessage(
                content=decision.reasoning,
                tool_calls=[
                    {"id": f"call_{i}", "name": tc["name"], "args": tc.get("args", {})}
                    for i, tc in enumerate(decision.tool_calls)
                ],
            )
        else:
            ai_msg = AIMessage(content=decision.answer or "")

        return {
            "messages": state["messages"] + [ai_msg],
            "iteration": state["iteration"] + 1,
        }


# ============================================================
# STREAMING PLANNER NODE
# ============================================================

class StreamingPlannerNode(Node):
    """
    Streams tokens to stdout while accumulating the full response.
    Falls back to PlannerNode structured output for the final message.
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
        print()  # newline after stream

        # Use the last chunk as the AIMessage (it has accumulated tool_calls)
        last = chunks[-1] if chunks else AIMessage(content="")
        return {
            "messages": state["messages"] + [last],
            "iteration": state["iteration"] + 1,
        }


# ============================================================
# ROUTER  (is a proper Node subclass)
# ============================================================

class RouterNode(Node):
    """
    Pure routing logic — reads state and returns the next node name.
    Implements Node so it participates in the same OOP contract.

    __call__ here is used as a LangGraph conditional-edge function,
    so it returns a str (node name) rather than a state delta.
    """

    async def __call__(self, state: AgentState) -> str:  # type: ignore[override]
        from langchain_core.messages import AIMessage

        # Hard cap: if we've hit max_iterations, force final regardless
        if state["iteration"] >= state["max_iterations"]:
            return "final"

        last = state["messages"][-1] if state["messages"] else None

        # Planner produced tool calls → execute them
        if isinstance(last, AIMessage) and last.tool_calls:
            return "executor"

        # Reflection says retry → re-plan
        reflection = state.get("reflection")
        if reflection and reflection.get("decision") == "retry":
            return "planner"

        # Otherwise → reflect on the answer before finalising
        return "reflection"


# ============================================================
# EXECUTOR NODE  (concurrent async tool dispatch)
# ============================================================

class ExecutorNode(Node):
    """
    Executes all pending tool calls concurrently via asyncio.gather().
    Appends one ToolMessage per call to the message history.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def __call__(self, state: AgentState) -> dict[str, Any]:
        from langchain_core.messages import AIMessage, ToolMessage

        last = state["messages"][-1]
        if not (isinstance(last, AIMessage) and last.tool_calls):
            return {}   # nothing to do

        async def _run_one(call: dict) -> ToolMessage:
            try:
                tool = self._registry.get(call["name"])
                result = await tool.execute(**call["args"])
            except KeyError:
                result = f"Error: unknown tool '{call['name']}'."
            except Exception as exc:
                result = f"Tool error: {exc}"
            return ToolMessage(content=result, tool_call_id=call["id"])

        tool_messages = await asyncio.gather(
            *[_run_one(call) for call in last.tool_calls]
        )

        return {"messages": state["messages"] + list(tool_messages)}


# ============================================================
# OFFLINE TOKEN COUNTER
# ============================================================

class OfflineTokenCounter:
    """
    Counts tokens without any API call or network access.

    Strategy (in priority order):
      1. tiktoken  — exact BPE counts matching OpenAI models (cl100k_base).
      2. Fallback  — len(text) // 4, the standard "4 chars ≈ 1 token" heuristic.

    tiktoken is a pure-Python C-extension; it runs entirely offline once
    the encoding file is cached locally (~1 MB, downloaded on first use).

    LangChain's trim_messages accepts any callable
        (list[BaseMessage]) -> int
    so this class exposes __call__ with that exact signature.
    """

    def __init__(self, model: str = "gpt-4o") -> None:
        self._enc = None
        try:
            import tiktoken
            # cl100k_base is the encoding for gpt-4, gpt-4o, gpt-3.5-turbo
            self._enc = tiktoken.encoding_for_model(model)
        except (ImportError, KeyError):
            # tiktoken not installed or unknown model — use char heuristic
            pass

    def count_text(self, text: str) -> int:
        """Count tokens in a single string."""
        if self._enc is not None:
            return len(self._enc.encode(text, disallowed_special=()))
        # fallback: 4 characters ≈ 1 token (OpenAI rule of thumb)
        return max(1, len(text) // 4)

    def __call__(self, messages: list) -> int:
        """
        Count total tokens across a list of BaseMessage objects.
        Called by LangChain's trim_messages as token_counter=self.
        Adds 4 tokens per message for role + formatting overhead
        (matches OpenAI's chat-completion token accounting).
        """
        total = 0
        for msg in messages:
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            total += self.count_text(content) + 4   # 4 = role + separators overhead
        return total


# ============================================================
# MEMORY NODE  (fully offline — no LLM needed for trimming)
# ============================================================

class MemoryNode(Node):
    """
    Trims the conversation history to stay within the token budget.

    Uses OfflineTokenCounter so no API call is made during trimming.
    trim_messages is called synchronously (it is not a coroutine when
    token_counter is a plain callable rather than a model).
    The __call__ is still async to satisfy the Node contract and keep
    the graph fully async-compatible.
    """

    def __init__(self, max_tokens: int = 8_000, model: str = "gpt-4o") -> None:
        self._max_tokens = max_tokens
        self._counter = OfflineTokenCounter(model=model)

    async def __call__(self, state: AgentState) -> dict[str, Any]:
        from langchain_core.messages import trim_messages

        # trim_messages is sync when token_counter is a callable (not a model)
        trimmed = trim_messages(
            state["messages"],
            token_counter=self._counter,   # pure offline callable
            max_tokens=self._max_tokens,
            strategy="last",
            include_system=True,
            start_on="human",
            end_on=("human", "tool"),
        )
        return {"messages": trimmed}


# ============================================================
# REFLECTION NODE  (structured output, no history pollution)
# ============================================================

class ReflectionNode(Node):
    """
    Evaluates the last assistant answer using structured output.

    Key fixes vs original:
    • Uses llm.with_structured_output(ReflectionDecision) — no JSON parsing.
    • The reflection prompt is sent as a separate one-shot call and does NOT
      mutate the main message history (no history pollution).
    • Max retries guard is enforced by the Router, not here.
    """

    _SYSTEM = (
        "You are a self-correction system. "
        "Evaluate the assistant's last answer for correctness and completeness. "
        "Return decision='ok' if the answer is satisfactory, 'retry' if it needs improvement."
    )

    def __init__(self, llm: Any) -> None:
        from langchain_core.messages import SystemMessage
        self._llm = llm.with_structured_output(ReflectionDecision)
        self._system = SystemMessage(content=self._SYSTEM)

    async def __call__(self, state: AgentState) -> dict[str, Any]:
        from langchain_core.messages import HumanMessage

        last_answer = (
            state["messages"][-1].content
            if state["messages"]
            else "(no answer yet)"
        )

        # One-shot call — does NOT append to state["messages"]
        decision: ReflectionDecision = await self._llm.ainvoke([
            self._system,
            HumanMessage(content=f"Evaluate this answer:\n\n{last_answer}"),
        ])

        return {"reflection": decision.model_dump()}


# ============================================================
# FINAL NODE
# ============================================================

class FinalNode(Node):
    """
    Extracts the last assistant message as the final answer.
    Writes to `final_answer` — a key declared in AgentState so
    LangGraph does not silently discard it.
    """

    async def __call__(self, state: AgentState) -> dict[str, Any]:
        last = state["messages"][-1] if state["messages"] else None
        answer = getattr(last, "content", "") or ""
        return {"final_answer": answer}


# ============================================================
# GRAPH BUILDER
# ============================================================

class AgentGraph:

    def __init__(
        self,
        planner: PlannerNode,
        streaming_planner: StreamingPlannerNode,
        router: RouterNode,
        executor: ExecutorNode,
        memory: MemoryNode,
        reflection: ReflectionNode,
        final: FinalNode,
        use_streaming: bool = False,
    ) -> None:
        self._planner = planner
        self._streaming_planner = streaming_planner
        self._router = router
        self._executor = executor
        self._memory = memory
        self._reflection = reflection
        self._final = final
        self._use_streaming = use_streaming

    def build(self) -> Any:
        """
        Graph topology
        --------------
        START
          └─► planner ──[tool calls?]──► executor ──► memory ──► planner (loop)
                      └─[no tools]────► reflection ──[ok]──────► final ──► END
                                                    └─[retry]──► planner
        """
        # langgraph import confined to graph builder
        from langgraph.graph import StateGraph, END

        graph = StateGraph(AgentState)

        active_planner = self._streaming_planner if self._use_streaming else self._planner

        graph.add_node("planner",    active_planner)
        graph.add_node("executor",   self._executor)
        graph.add_node("memory",     self._memory)
        graph.add_node("reflection", self._reflection)
        graph.add_node("final",      self._final)

        graph.set_entry_point("planner")

        # Router is called as a conditional-edge function (returns a node name string)
        graph.add_conditional_edges(
            "planner",
            self._router,           # RouterNode.__call__ returns str — correct
            {
                "executor":   "executor",
                "reflection": "reflection",
                "final":      "final",    # hit when max_iterations reached mid-plan
                "planner":    "planner",  # reflection retry re-enters planner
            },
        )

        graph.add_edge("executor", "memory")
        graph.add_edge("memory",   "planner")

        graph.add_conditional_edges(
            "reflection",
            lambda s: "planner" if (s.get("reflection") or {}).get("decision") == "retry" else "final",
            {"planner": "planner", "final": "final"},
        )

        graph.add_edge("final", END)

        return graph.compile()


# ============================================================
# FACTORY — single composition root
# ============================================================

def build_agent(
    llm: Any,
    database: Any,
    sql_dialect: str = "oracle",
    max_tokens: int = 8_000,
    max_iterations: int = 10,
    use_streaming: bool = False,
    llm_model: str = "gpt-4o",
) -> tuple[Any, dict]:
    """
    Wire all dependencies and return (compiled_graph, initial_state_template).

    Parameters
    ----------
    llm            : any LangChain chat model (ChatOpenAI, ChatAnthropic, …)
    database       : object with async `execute(sql: str) -> Any` method
    sql_dialect    : sqlglot source dialect (default "oracle")
    max_tokens     : memory trim budget in tokens
    max_iterations : hard cap on planner→executor cycles
    use_streaming  : use StreamingPlannerNode instead of PlannerNode
    llm_model      : model name used by OfflineTokenCounter for tiktoken encoding
    """
    registry = ToolRegistry([
        SQLToolCapability(database, default_dialect=sql_dialect),
        PythonToolCapability(),
    ])

    graph = AgentGraph(
        planner=PlannerNode(llm),
        streaming_planner=StreamingPlannerNode(llm),
        router=RouterNode(),
        executor=ExecutorNode(registry),
        memory=MemoryNode(max_tokens=max_tokens, model=llm_model),  # no llm needed
        reflection=ReflectionNode(llm),
        final=FinalNode(),
        use_streaming=use_streaming,
    ).build()

    initial_state: AgentState = {
        "messages": [],
        "reflection": None,
        "session_id": "",        # caller sets this per-run
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

    # ── Mock LLM ──────────────────────────────────────────────────────────────
    class MockStructuredLLM:
        """Simulates a LangChain chat model with structured output support."""

        def __init__(self, schema: type[BaseModel] | None = None):
            self._schema = schema

        def with_structured_output(self, schema: type[BaseModel]) -> "MockStructuredLLM":
            return MockStructuredLLM(schema=schema)

        async def ainvoke(self, messages: list, **_: Any) -> Any:
            if self._schema is PlannerDecision:
                return PlannerDecision(
                    reasoning="The user asked a simple question I can answer directly.",
                    tool_calls=[],
                    answer="The answer is 42.",
                )
            if self._schema is ReflectionDecision:
                return ReflectionDecision(decision="ok", critique="Answer is correct.")
            from langchain_core.messages import AIMessage
            return AIMessage(content="streamed response")

        async def astream(self, messages: list, **_: Any):
            from langchain_core.messages import AIMessage
            for token in ["stream", "ed ", "ok"]:
                yield AIMessage(content=token)

    # ── Mock Database ─────────────────────────────────────────────────────────
    class MockDB:
        async def execute(self, sql: str) -> str:
            return f"[mock result for: {sql[:60]}]"

    # ── Wire & run ────────────────────────────────────────────────────────────
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
            llm_model="gpt-4o",
        )

        state = {
            **state_template,
            "session_id": str(uuid.uuid4()),
            "messages": [HumanMessage(content="What is the meaning of life?")],
        }

        result = await graph.ainvoke(state)

        print("\n=== AGENT RESULT ===")
        print(f"Answer      : {result['final_answer']}")
        print(f"Iterations  : {result['iteration']}")
        print(f"Reflection  : {result['reflection']}")
        print("Agent ran successfully ✓")

    asyncio.run(main())
