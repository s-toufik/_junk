"""
Agent Framework for ReAct-style reasoning with tools.
Supports SQL queries and Python code execution.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


# ==================== Enums ====================


class ToolType(Enum):
    """Available tool types for the agent."""
    SQL = "sql"
    PYTHON = "python"


class QueryStatus(Enum):
    """Status of the agent session."""
    SUCCESS = "success"
    VALIDATION_ERROR = "validation_error"
    EXECUTION_ERROR = "execution_error"
    ITERATION_LIMIT = "iteration_limit"
    ERROR = "error"


# ==================== Dataclasses ====================


@dataclass
class ToolResult:
    """Result from executing a tool."""
    tool_type: ToolType
    content: str
    success: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentStep:
    """A step planned by the LLM."""
    step_type: str  # "tool" or "answer"
    tool_type: Optional[ToolType] = None
    tool_input: Optional[str] = None
    reasoning: str = ""
    answer: Optional[str] = None


@dataclass
class AgentTurn:
    """A turn in the conversation history."""
    role: str  # user, assistant, tool_result
    content: str


@dataclass
class AgentSession:
    """Maintains the state of an agent session."""
    question: str
    history: List[AgentTurn] = field(default_factory=list)
    collected_results: List[ToolResult] = field(default_factory=list)
    iterations: int = 0
    final_answer: Optional[str] = None
    status: QueryStatus = QueryStatus.SUCCESS


# ==================== Base Tool ====================


class Tool:
    """Base class for all tools."""
    tool_type: ToolType

    def execute(self, input_data: str) -> ToolResult:
        """Execute the tool with given input."""
        raise NotImplementedError("Subclasses must implement execute")


# ==================== SqlTool ====================


class SqlTool(Tool):
    """Tool for executing SQL queries with validation and limits."""

    tool_type = ToolType.SQL

    def __init__(
        self,
        query_executor: Any,  # QueryExecutor
        validation_service: Any = None,  # SqlValidationService
        limit_service: Any = None,  # LimitInjectionService
        schema_repo: Any = None,  # SchemaRepository
    ) -> None:
        self._executor = query_executor
        self._validator = validation_service or SqlValidationService()  # Assume imported
        self._limiter = limit_service or LimitInjectionService()
        self._schema_repo = schema_repo

    def execute(self, sql: str) -> ToolResult:
        """Execute SQL with validation, limit injection, and execution."""
        try:
            # Validate
            validated = self._validator.validate(sql)

            # Inject LIMIT
            limited, was_limited = self._limiter.apply(validated)

            # Execute
            result = self._executor.execute(limited)
            result.truncated = was_limited

            result_summary = f"[SQL RESULT]\n{result.as_text_table() if hasattr(result, 'as_text_table') else str(result)}"

            return ToolResult(
                tool_type=self.tool_type,
                content=result_summary,
                success=True,
                metadata={"sql": limited.normalised if hasattr(limited, 'normalised') else sql, "truncated": was_limited}
            )
        except Exception as exc:  # noqa: BLE001
            error_msg = f"[SQL ERROR] {exc}"
            return ToolResult(
                tool_type=self.tool_type,
                content=error_msg,
                success=False,
                metadata={"error": str(exc)}
            )


# ==================== PythonTool ====================


class PythonTool(Tool):
    """Tool for safe Python code execution."""

    tool_type = ToolType.PYTHON

    def __init__(self):
        # Safe execution environment setup would go here
        pass

    def execute(self, code: str) -> ToolResult:
        """Execute Python code safely, capture stdout, support DataFrames and matplotlib."""
        try:
            # Placeholder for safe execution logic
            # Would use restricted globals, capture output, etc.
            local_vars = {}
            exec(code, {"__builtins__": {}}, local_vars)  # Restricted for safety

            # Capture output (simplified)
            output = "Python execution completed."
            if 'df' in local_vars and hasattr(local_vars['df'], 'to_string'):
                output += "\nDataFrame:\n" + local_vars['df'].to_string()

            return ToolResult(
                tool_type=self.tool_type,
                content=output,
                success=True,
                metadata={"code_executed": True}
            )
        except Exception as exc:
            return ToolResult(
                tool_type=self.tool_type,
                content=f"[PYTHON ERROR] {exc}",
                success=False,
                metadata={"error": str(exc)}
            )


# ==================== ToolRegistry ====================


class ToolRegistry:
    """Registry of available tools."""

    def __init__(self):
        self.tools: Dict[ToolType, Tool] = {}

    def register_tool(self, tool: Tool) -> None:
        self.tools[tool.tool_type] = tool

    def get_tool(self, tool_type: ToolType) -> Optional[Tool]:
        return self.tools.get(tool_type)

    def list_tools(self) -> List[str]:
        return [t.value for t in self.tools.keys()]


# ==================== AskQuestionUseCase ====================


class AskQuestionUseCase:
    """Generalized agent use case supporting multiple tools."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        llm: Any,  # LlmPort
        schema_repo: Any = None,
        max_iterations: int = 10,
    ) -> None:
        self._registry = tool_registry
        self._llm = llm
        self._schema_repo = schema_repo
        self._max_iter = max_iterations

    def ask(self, question: str) -> AgentSession:
        session = AgentSession(question=question)
        session.history.append(AgentTurn(role="user", content=question))

        schema = self._schema_repo.load_schema() if self._schema_repo else None
        log.debug("Schema loaded: %s", schema.table_names() if schema else "No schema")

        lm_history: List[Dict[str, str]] = []

        while session.iterations < self._max_iter:
            session.iterations += 1
            log.debug("Iteration %d/%d", session.iterations, self._max_iter)

            # Ask LLM for next step
            step = self._llm.plan_next_step(
                question=question,
                schema=schema,
                collected_results=session.collected_results,
                history=lm_history,
                available_tools=[t.value for t in ToolType],
            )
            log.debug("Step: %s | Reasoning: %s", step.step_type, step.reasoning)

            # ANSWER branch
            if step.step_type == "answer":
                session.final_answer = step.answer
                session.status = QueryStatus.SUCCESS
                session.history.append(
                    AgentTurn(role="assistant", content=step.answer or "")
                )
                log.debug("Final answer after %d iteration(s).", session.iterations)
                return session

            # TOOL branch
            if step.tool_type and step.tool_input:
                tool = self._registry.get_tool(step.tool_type)
                if not tool:
                    error_msg = f"[TOOL ERROR] Unknown tool: {step.tool_type}"
                    session.history.append(AgentTurn(role="tool_result", content=error_msg))
                    lm_history.append({"role": "user", content=error_msg})
                    continue

                session.history.append(
                    AgentTurn(
                        role="assistant",
                        content=f"[REASONING] {step.reasoning}\n[TOOL {step.tool_type.value}] {step.tool_input}",
                    )
                )
                lm_history.append({"role": "assistant", "content": f"[TOOL] {step.tool_input}"})

                # Execute tool
                result = tool.execute(step.tool_input)
                session.collected_results.append(result)
                session.status = QueryStatus.SUCCESS if result.success else QueryStatus.EXECUTION_ERROR

                # Feed result back
                result_summary = f"[RESULT from {result.tool_type.value}]\n{result.content}"
                session.history.append(
                    AgentTurn(role="tool_result", content=result_summary)
                )
                lm_history.append({"role": "user", "content": result_summary})

            else:
                # Fallback
                continue

        # Iteration limit
        session.status = QueryStatus.ITERATION_LIMIT
        session.final_answer = (
            f"Could not answer the question after {self._max_iter} attempts. "
            "Try rephrasing or simplifying the question."
        )
        return session


# ==================== Example usage ====================

if __name__ == "__main__":
    # Example setup (placeholders)
    # llm = LlmPort()
    # schema_repo = SchemaRepository()
    # query_executor = QueryExecutor()

    # registry = ToolRegistry()
    # registry.register_tool(SqlTool(query_executor=query_executor, schema_repo=schema_repo))
    # registry.register_tool(PythonTool())

    # use_case = AskQuestionUseCase(registry, llm, schema_repo)
    # session = use_case.ask("What are the top employees by salary?")
    # print(session.final_answer)
    print("Agent framework ready. Configure dependencies for full usage.")
