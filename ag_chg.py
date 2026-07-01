from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Literal

import asyncio
import json
import sqlglot

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from langchain_core.tools import BaseTool
from langchain_core.messages import BaseMessage, AIMessage, ToolMessage
from langchain_core.messages.utils import trim_messages

from langgraph.graph import StateGraph, END


# ============================================================
# STATE
# ============================================================

class AgentState(TypedDict, total=False):
    messages: List[BaseMessage]
    reflection: Dict[str, Any]
    answer: str


# ============================================================
# SCHEMAS
# ============================================================

class SQLToolSchema(BaseModel):
    query: str = Field(...)


class PythonToolSchema(BaseModel):
    code: str = Field(...)


class ReflectionDecisionSchema(BaseModel):
    decision: Literal["ok", "retry"]
    critique: str


# ============================================================
# TOOL CORE (ASYNC CAPABLE)
# ============================================================

class ToolCapability(ABC):

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def args_schema(self): ...

    @abstractmethod
    async def execute(self, **kwargs) -> Any: ...


# ============================================================
# SQL TOOL (ASYNC SAFE)
# ============================================================

class SQLToolCapability(ToolCapability):

    ALLOWED_STATEMENTS = {"select"}

    def __init__(self, database):
        self.database = database

    @property
    def name(self) -> str:
        return "sql"

    @property
    def description(self) -> str:
        return "Async safe SQL execution (SELECT only)"

    @property
    def args_schema(self):
        return SQLToolSchema

    async def execute(self, **kwargs) -> Any:
        query = kwargs["query"]

        ast = sqlglot.parse_one(query)
        if ast.key.lower() not in self.ALLOWED_STATEMENTS:
            raise ValueError("Only SELECT allowed")

        normalized = ast.sql(dialect="postgres")

        # assume DB is async-compatible
        return await self.database.execute(normalized)


# ============================================================
# PYTHON TOOL (ASYNC SANDBOX VIA THREAD POOL)
# ============================================================

class PythonToolCapability(ToolCapability):

    def __init__(self):
        pass

    @property
    def name(self) -> str:
        return "python"

    @property
    def description(self) -> str:
        return "Async sandboxed Python execution"

    @property
    def args_schema(self):
        return PythonToolSchema

    async def execute(self, **kwargs) -> Any:
        code = kwargs["code"]

        def _run():
            safe_builtins = {
                "len": len,
                "range": range,
                "min": min,
                "max": max,
                "sum": sum,
                "print": print,
            }

            globals_dict = {"__builtins__": safe_builtins}
            locals_dict = {}

            exec(code, globals_dict, locals_dict)
            return locals_dict

        return await asyncio.to_thread(_run)


# ============================================================
# TOOL REGISTRY
# ============================================================

class ToolRegistry:

    def __init__(self, tools: List[ToolCapability]):
        self.tools = {t.name: t for t in tools}

    def get(self, name: str) -> ToolCapability:
        return self.tools[name]


# ============================================================
# NODES
# ============================================================

class Node(ABC):
    @abstractmethod
    async def __call__(self, state: AgentState) -> Dict[str, Any]:
        ...


# ============================================================
# PLANNER
# ============================================================

class PlannerNode(Node):

    def __init__(self, llm):
        self.llm = llm

    async def __call__(self, state: AgentState):
        response = await self.llm.ainvoke(state["messages"])
        return {"messages": [response]}


# ============================================================
# STREAMING PLANNER (ASYNC FIXED)
# ============================================================

class StreamingPlannerNode(Node):

    def __init__(self, llm):
        self.llm = llm

    async def __call__(self, state: AgentState):

        chunks = []

        async for c in self.llm.astream(state["messages"]):
            chunks.append(c)
            print(c.content, end="", flush=True)

        full = AIMessage(content="".join([c.content for c in chunks]))

        return {"messages": [full]}


# ============================================================
# ROUTER (SINGLE SOURCE OF TRUTH)
# ============================================================

class RouterNode:

    def route(self, state: AgentState) -> str:
        last = state["messages"][-1]

        if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
            return "tool"

        return "reflection"


# ============================================================
# EXECUTOR (ASYNC PARALLEL TOOL EXECUTION READY)
# ============================================================

class ExecutorNode(Node):

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def __call__(self, state: AgentState):

        last = state["messages"][-1]

        if not isinstance(last, AIMessage) or not getattr(last, "tool_calls", None):
            return {"messages": []}

        async def run_call(call):
            tool = self.registry.get(call["name"])
            result = await tool.execute(**call["args"])

            return ToolMessage(
                content=str(result),
                tool_call_id=call["id"],
            )

        results = await asyncio.gather(*[
            run_call(call) for call in last.tool_calls
        ])

        return {"messages": list(results)}


# ============================================================
# MEMORY
# ============================================================

class MemoryNode(Node):

    def __init__(self, llm, max_tokens: int = 8000):
        self.llm = llm
        self.max_tokens = max_tokens

    async def __call__(self, state: AgentState):

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
# REFLECTION
# ============================================================

class ReflectionNode(Node):

    def __init__(self, llm):
        self.llm = llm

    async def __call__(self, state: AgentState):

        last = state["messages"][-1].content

        prompt = [
            *state["messages"],
            AIMessage(content=json.dumps({
                "answer": last,
                "instruction": "evaluate correctness"
            }))
        ]

        result = await self.llm.ainvoke(prompt)

        try:
            data = json.loads(result.content)
        except Exception:
            data = {"decision": "retry", "critique": "invalid format"}

        return {"reflection": ReflectionDecisionSchema(**data).model_dump()}


# ============================================================
# FINAL NODE
# ============================================================

class FinalNode(Node):

    async def __call__(self, state: AgentState):
        return {"answer": state["messages"][-1].content}


# ============================================================
# GRAPH BUILDER (ASYNC READY)
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

        planner_node = self.streaming_planner if self.use_streaming else self.planner

        graph.add_node("planner", planner_node)
        graph.add_node("executor", self.executor)
        graph.add_node("memory", self.memory)
        graph.add_node("reflection", self.reflection)
        graph.add_node("final", self.final)

        graph.set_entry_point("planner")

        # SINGLE ROUTING PATH
        graph.add_conditional_edges(
            "planner",
            self.router.route,
            {
                "tool": "executor",
                "reflection": "reflection",
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