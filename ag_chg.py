"""
===========================================================
FULL LLM AGENT ARCHITECTURE (LangGraph + Reflection Loop)
===========================================================

FEATURES:
✔ Hexagonal Tool Design
✔ Pydantic v2 Tool Schemas
✔ SQLGlot SQL Tool
✔ Python Execution Tool
✔ LangChain Tool Adapter
✔ Tool Registry
✔ Planner (sync + streaming)
✔ Router
✔ Executor
✔ Memory Node (trim context)
✔ Reflection Node (self-correction loop)
✔ Final Node
✔ LangGraph orchestration
===========================================================
"""

# ============================================================
# IMPORTS
# ============================================================

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List

import sqlglot

from pydantic import BaseModel, Field

from langchain_core.tools import BaseTool
from langchain_core.messages import BaseMessage, AIMessage, ToolMessage
from langchain_core.messages.utils import trim_messages

from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict


# ============================================================
# STATE
# ============================================================

class AgentState(TypedDict):
    messages: List[BaseMessage]
    reflection: Dict[str, Any] | None


# ============================================================
# PYDANTIC TOOL SCHEMAS
# ============================================================

class SQLToolSchema(BaseModel):
    query: str = Field(..., description="SQL query to execute")


class PythonToolSchema(BaseModel):
    code: str = Field(..., description="Python code to execute")


class ReflectionDecisionSchema(BaseModel):
    decision: str = Field(..., description="'ok' or 'retry'")
    critique: str = Field(..., description="Why result is good or bad")


# ============================================================
# TOOL PORT (HEXAGONAL CORE)
# ============================================================

class ToolCapability(ABC):

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        ...

    @property
    @abstractmethod
    def args_schema(self):
        ...

    @abstractmethod
    def execute(self, **kwargs) -> Any:
        ...


# ============================================================
# SQL TOOL
# ============================================================

class SQLToolCapability(ToolCapability):

    def __init__(self, database):
        self.database = database

    @property
    def name(self) -> str:
        return "sql"

    @property
    def description(self) -> str:
        return "Execute SQL using AST validation (sqlglot)"

    @property
    def args_schema(self):
        return SQLToolSchema

    def execute(self, **kwargs) -> Any:

        query = kwargs["query"]

        ast = sqlglot.parse_one(query)

        normalized = ast.sql(dialect="postgres")

        return self.database.execute(normalized)


# ============================================================
# PYTHON TOOL
# ============================================================

class PythonToolCapability(ToolCapability):

    def __init__(self, safe: bool = True):
        self.safe = safe

    @property
    def name(self) -> str:
        return "python"

    @property
    def description(self) -> str:
        return "Execute Python code"

    @property
    def args_schema(self):
        return PythonToolSchema

    def execute(self, **kwargs) -> Any:

        code = kwargs["code"]

        namespace = {}

        exec(code, {}, namespace)

        return namespace


# ============================================================
# LANGCHAIN ADAPTER
# ============================================================

class LangChainToolAdapter(BaseTool):

    capability: ToolCapability

    def __init__(self, capability: ToolCapability):
        super().__init__(
            name=capability.name,
            description=capability.description,
            args_schema=capability.args_schema,
        )
        self.capability = capability

    def _run(self, **kwargs):
        return self.capability.execute(**kwargs)


# ============================================================
# TOOL REGISTRY
# ============================================================

class ToolRegistry:

    def __init__(self, tools: List[ToolCapability]):
        self.tools = {t.name: t for t in tools}

    def get(self, name: str) -> ToolCapability:
        return self.tools[name]

    def langchain_tools(self):
        return [LangChainToolAdapter(t) for t in self.tools.values()]


# ============================================================
# BASE NODE
# ============================================================

class Node(ABC):

    @abstractmethod
    def __call__(self, state: AgentState) -> Dict[str, Any]:
        ...


# ============================================================
# PLANNER (SYNC)
# ============================================================

class PlannerNode(Node):

    def __init__(self, llm):
        self.llm = llm

    def __call__(self, state: AgentState):

        response = self.llm.invoke(state["messages"])

        return {"messages": [response]}


# ============================================================
# PLANNER (STREAMING)
# ============================================================

class StreamingPlannerNode(Node):

    def __init__(self, llm):
        self.llm = llm

    def __call__(self, state: AgentState):

        chunks = []

        for c in self.llm.stream(state["messages"]):
            chunks.append(c)
            print(c.content, end="", flush=True)

        return {"messages": [chunks[-1]]}


# ============================================================
# ROUTER
# ============================================================

class RouterNode:

    def route(self, state: AgentState) -> str:

        last = state["messages"][-1]

        if isinstance(last, AIMessage) and last.tool_calls:
            return "tool"

        if state.get("reflection") and state["reflection"]["decision"] == "retry":
            return "planner"

        return "reflection"


# ============================================================
# EXECUTOR
# ============================================================

class ExecutorNode(Node):

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def __call__(self, state: AgentState):

        last = state["messages"][-1]

        outputs = []

        for call in last.tool_calls:

            tool = self.registry.get(call["name"])

            result = tool.execute(**call["args"])

            outputs.append(
                ToolMessage(
                    content=str(result),
                    tool_call_id=call["id"],
                )
            )

        return {"messages": outputs}


# ============================================================
# MEMORY NODE (TRIM)
# ============================================================

class MemoryNode(Node):

    def __init__(self, llm, max_tokens: int = 8000):
        self.llm = llm
        self.max_tokens = max_tokens

    def __call__(self, state: AgentState):

        trimmed = trim_messages(
            state["messages"],
            token_counter=self.llm,
            max_tokens=self.max_tokens,
            strategy="last",
            include_system=True,
            start_on="human",
            end_on=("human", "tool"),
        )

        return {"messages": trimmed}


# ============================================================
# REFLECTION NODE (SELF-CORRECTION LOOP)
# ============================================================

class ReflectionNode(Node):

    def __init__(self, llm):
        self.llm = llm

    def __call__(self, state: AgentState):

        last = state["messages"][-1].content

        prompt = [
            *state["messages"],
            AIMessage(content=f"""
You are a reflection system.

Evaluate the last answer:
- correctness
- completeness
- tool usage

Return STRICT JSON:
{{
  "decision": "ok" | "retry",
  "critique": "..."
}}

ANSWER:
{last}
""")
        ]

        result = self.llm.invoke(prompt)

        import json

        try:
            data = json.loads(result.content)
        except Exception:
            data = {"decision": "retry", "critique": "invalid format"}

        decision = ReflectionDecisionSchema(**data)

        return {
            "reflection": decision.model_dump()
        }


# ============================================================
# FINAL NODE
# ============================================================

class FinalNode(Node):

    def __call__(self, state: AgentState):

        return {
            "answer": state["messages"][-1].content
        }


# ============================================================
# GRAPH BUILDER
# ============================================================

class AgentGraph:

    def __init__(
        self,
        planner,
        streaming_planner,
        router,
        executor,
        memory,
        reflection,
        final,
        use_streaming: bool = False,
    ):
        self.planner = planner
        self.streaming_planner = streaming_planner
        self.router = router
        self.executor = executor
        self.memory = memory
        self.reflection = reflection
        self.final = final
        self.use_streaming = use_streaming

    def build(self):

        graph = StateGraph(AgentState)

        planner_node = (
            self.streaming_planner
            if self.use_streaming
            else self.planner
        )

        graph.add_node("planner", planner_node)
        graph.add_node("executor", self.executor)
        graph.add_node("memory", self.memory)
        graph.add_node("reflection", self.reflection)
        graph.add_node("final", self.final)

        graph.set_entry_point("planner")

        graph.add_conditional_edges(
            "planner",
            self.router.route,
            {
                "tool": "executor",
                "reflection": "reflection",
                "planner": "planner",
            },
        )

        graph.add_edge("executor", "memory")
        graph.add_edge("memory", "planner")

        graph.add_conditional_edges(
            "reflection",
            lambda s: "planner" if s["reflection"]["decision"] == "retry" else "final",
            {
                "planner": "planner",
                "final": "final",
            },
        )

        graph.add_edge("final", END)

        return graph.compile()


# ============================================================
# EXAMPLE USAGE
# ============================================================

if __name__ == "__main__":

    # ---------------- LLM MOCK ----------------
    class MockLLM:
        def invoke(self, x):
            return AIMessage(content="final", tool_calls=[])

        def stream(self, x):
            for i in ["step1", "step2", "done"]:
                yield AIMessage(content=i)

    llm = MockLLM()

    # ---------------- DB MOCK ----------------
    class DB:
        def execute(self, sql):
            return f"executed: {sql}"

    db = DB()

    # ---------------- TOOLS ----------------
    registry = ToolRegistry([
        SQLToolCapability(db),
        PythonToolCapability()
    ])

    # ---------------- NODES ----------------
    planner = PlannerNode(llm)
    streaming = StreamingPlannerNode(llm)
    router = RouterNode()
    executor = ExecutorNode(registry)
    memory = MemoryNode(llm)
    reflection = ReflectionNode(llm)
    final = FinalNode()

    # ---------------- GRAPH ----------------
    app = AgentGraph(
        planner,
        streaming,
        router,
        executor,
        memory,
        reflection,
        final,
        use_streaming=True
    ).build()

    print("Agent built successfully")