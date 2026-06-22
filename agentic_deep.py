"""
agent.py — ReAct Agent with Tool Support
=========================================

This module implements a ReAct agent that can use multiple tools (SQL, Python)
to answer questions. The agent iterates between tool calls and a final answer.

Structure:
- Enums: ToolType, QueryStatus
- Dataclasses: ToolResult, AgentStep, AgentSession, AgentTurn
- Base Tool: Tool (ABC)
- SqlTool: executes SQL with validation, pagination, and automatic LIMIT
- PythonTool: executes Python code safely, captures stdout, supports DataFrames and matplotlib
- ToolRegistry: registers and retrieves tools by name
- AskQuestionUseCase: orchestrates the ReAct loop
- Example usage (if run as script)
"""

from __future__ import annotations

import logging
import sys
import io
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

# Import existing domain services and ports (assuming they are available)
from application.port.outbound.ports import LlmPort, QueryExecutor, SchemaRepository
from domain.service.sql_services import (
    LimitInjectionService,
    SqlValidationError,
    SqlValidationService,
)

log = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================

class ToolType(Enum):
    SQL = "sql"
    PYTHON = "python"


class QueryStatus(Enum):
    """Status of the agent session."""
    SUCCESS = "success"
    VALIDATION_ERROR = "validation_error"
    EXECUTION_ERROR = "execution_error"
    ITERATION_LIMIT = "iteration_limit"


# =============================================================================
# Dataclasses
# =============================================================================

@dataclass
class ToolResult:
    """Result of executing a tool."""
    tool_name: str
    success: bool
    data: Any = None               # Structured data (rows, DataFrame, etc.)
    error: Optional[str] = None
    stdout: Optional[str] = None   # Captured stdout (mainly for Python)
    truncated: bool = False        # Whether the result was truncated (e.g., LIMIT)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_text_table(self) -> str:
        """Return a human-readable representation of the result."""
        if not self.success:
            return f"Error: {self.error}"
        if self.data is None:
            return "No data returned."
        # If data is a list of dicts, format as a simple table
        if isinstance(self.data, list) and all(isinstance(row, dict) for row in self.data):
            if not self.data:
                return "Empty result set."
            headers = self.data[0].keys()
            rows = [[str(row.get(h, "")) for h in headers] for row in self.data]
            col_widths = [max(len(h), max((len(row[i]) for row in rows), default=0)) for i, h in enumerate(headers)]
            fmt = " | ".join(f"{{:<{w}}}" for w in col_widths)
            lines = [fmt.format(*headers)]
            lines.append("-+-".join("-" * w for w in col_widths))
            for row in rows:
                lines.append(fmt.format(*row))
            return "\n".join(lines)
        # If data is a pandas DataFrame, use its string representation
        if hasattr(self.data, "to_string"):
            return str(self.data)
        # Fallback
        return str(self.data)


@dataclass
class AgentStep:
    """One planning step returned by the LLM."""
    step_type: str                  # "ANSWER" or "TOOL_CALL"
    reasoning: str
    answer: Optional[str] = None    # Only for ANSWER
    tool_name: Optional[str] = None # Only for TOOL_CALL
    tool_args: Dict[str, Any] = field(default_factory=dict)  # Only for TOOL_CALL


@dataclass
class AgentTurn:
    """A turn in the conversation history."""
    role: str          # "user", "assistant", "tool_result"
    content: str


@dataclass
class AgentSession:
    """Holds the state of a single agent run."""
    question: str
    history: List[AgentTurn] = field(default_factory=list)
    collected_results: List[ToolResult] = field(default_factory=list)
    final_answer: Optional[str] = None
    status: QueryStatus = QueryStatus.SUCCESS
    iterations: int = 0


# =============================================================================
# Base Tool
# =============================================================================

class Tool(ABC):
    """Abstract base class for tools that the agent can use."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name of the tool."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what the tool does."""
        pass

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """JSON Schema describing the parameters for this tool."""
        pass

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with the given arguments."""
        pass

    def to_openai_function(self) -> Dict[str, Any]:
        """Convert tool to an OpenAI function definition (for LLM prompting)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }


# =============================================================================
# SqlTool
# =============================================================================

class SqlTool(Tool):
    """
    SQL tool that validates, injects LIMIT, and executes queries.
    Supports pagination via LIMIT/OFFSET.
    """

    def __init__(
        self,
        query_executor: QueryExecutor,
        schema_repo: SchemaRepository,
        validation_service: Optional[SqlValidationService] = None,
        limit_service: Optional[LimitInjectionService] = None,
        default_limit: int = 100,
        max_limit: int = 10000,
    ):
        self._executor = query_executor
        self._schema_repo = schema_repo
        self._validator = validation_service or SqlValidationService()
        self._limiter = limit_service or LimitInjectionService()
        self._default_limit = default_limit
        self._max_limit = max_limit

    @property
    def name(self) -> str:
        return "sql"

    @property
    def description(self) -> str:
        return "Execute SQL queries against the database. Use this to retrieve data."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "The SQL query to execute. Must be a SELECT statement.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of rows to return (overrides any LIMIT in the SQL).",
                    "minimum": 1,
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of rows to skip (for pagination).",
                    "minimum": 0,
                },
            },
            "required": ["sql"],
        }

    def execute(self, **kwargs) -> ToolResult:
        sql = kwargs.get("sql", "")
        limit = kwargs.get("limit")
        offset = kwargs.get("offset", 0)

        # Validate
        try:
            validated = self._validator.validate(sql)
        except SqlValidationError as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"SQL validation error: {exc}",
            )

        # Inject limit/offset if requested
        final_sql = validated.normalised
        if limit is not None:
            # Override any existing LIMIT
            # We'll use a simple heuristic: replace or add LIMIT clause.
            # For simplicity, we use the LimitInjectionService which adds a limit
            # but we need to handle offset as well.
            # We'll reparse and use the limiter's apply_limit method.
            # Since LimitInjectionService may not support offset, we'll
            # construct the SQL manually with LIMIT and OFFSET.
            # Quick implementation: append LIMIT and OFFSET.
            # Better: use a proper SQL parser, but we'll keep it simple.
            if limit > self._max_limit:
                limit = self._max_limit
            # We need to ensure the SQL is a SELECT and doesn't already have LIMIT.
            # We'll remove any existing LIMIT clause (naive).
            # Use regex to remove LIMIT clause.
            import re
            # Remove LIMIT clause (case-insensitive)
            sql_clean = re.sub(r"\s+LIMIT\s+\d+(\s+OFFSET\s+\d+)?", "", final_sql, flags=re.IGNORECASE)
            # Add LIMIT and OFFSET
            if offset:
                final_sql = f"{sql_clean} LIMIT {limit} OFFSET {offset}"
            else:
                final_sql = f"{sql_clean} LIMIT {limit}"
        else:
            # Apply auto-limit to avoid huge results
            final_sql, was_limited = self._limiter.apply(validated)
            if was_limited:
                log.debug("Auto-LIMIT applied to SQL: %s", final_sql)

        # Execute
        try:
            result = self._executor.execute(final_sql)
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Database error: {exc}",
            )

        # Convert result to list of dicts if needed
        data = result.rows if hasattr(result, "rows") else result

        return ToolResult(
            tool_name=self.name,
            success=True,
            data=data,
            truncated=result.truncated if hasattr(result, "truncated") else False,
            metadata={
                "sql": final_sql,
                "row_count": len(data) if isinstance(data, list) else 0,
            }
        )


# =============================================================================
# PythonTool
# =============================================================================

class PythonTool(Tool):
    """
    Python tool that executes code in a restricted environment.
    Captures stdout, supports pandas DataFrames and matplotlib (non-interactive).
    """

    def __init__(self, timeout: int = 10):
        self._timeout = timeout
        self._allowed_imports = {
            "pandas": "pd",
            "numpy": "np",
            "matplotlib.pyplot": "plt",
            "matplotlib": "mpl",
            "json": "json",
            "math": "math",
            "datetime": "datetime",
            "re": "re",
            "statistics": "statistics",
            "collections": "collections",
            "itertools": "itertools",
            "functools": "functools",
        }

    @property
    def name(self) -> str:
        return "python"

    @property
    def description(self) -> str:
        return (
            "Execute Python code for data analysis, calculations, or visualization. "
            "The code can use pandas, numpy, matplotlib (non-interactive). "
            "The last expression's value (if any) is returned as the result."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The Python code to execute.",
                }
            },
            "required": ["code"],
        }

    def execute(self, **kwargs) -> ToolResult:
        code = kwargs.get("code", "")

        # Prepare restricted globals
        globals_dict = {}
        # Add allowed imports
        for module_name, alias in self._allowed_imports.items():
            try:
                if alias:
                    globals_dict[alias] = __import__(module_name)
                else:
                    globals_dict[module_name] = __import__(module_name)
            except ImportError:
                pass

        # Add builtins that are safe
        safe_builtins = {
            "abs": abs,
            "all": all,
            "any": any,
            "bool": bool,
            "dict": dict,
            "enumerate": enumerate,
            "float": float,
            "int": int,
            "len": len,
            "list": list,
            "max": max,
            "min": min,
            "print": print,
            "range": range,
            "round": round,
            "set": set,
            "sorted": sorted,
            "str": str,
            "sum": sum,
            "tuple": tuple,
            "zip": zip,
        }
        globals_dict["__builtins__"] = safe_builtins

        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()

        try:
            # Execute the code
            exec(code, globals_dict)
            # Check if the last line produced a value (like in an interactive session)
            # We'll capture any variable named '_' or the result of the last expression.
            # A common approach: compile with single mode to get the last expression.
            # Instead, we'll try to compile as a single statement to capture the last expression's value.
            # We'll use a trick: wrap code in a function and capture return value,
            # but for simplicity we'll just get the stdout and any variable named '_result'.
            # Alternative: we can execute and then look for '_' in globals.
            # We'll just return stdout and any DataFrame if present.
            captured = sys.stdout.getvalue()
            # Look for a variable named 'result' or 'df'
            data = None
            if "result" in globals_dict:
                data = globals_dict["result"]
            elif "df" in globals_dict:
                data = globals_dict["df"]
            elif "_" in globals_dict:
                data = globals_dict["_"]
            # If no data, but stdout has content, use that as data
            if data is None and captured:
                data = captured.strip()
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=data,
                stdout=captured,
            )
        except Exception as exc:
            # Capture any error
            error_msg = str(exc)
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=error_msg,
                stdout=sys.stdout.getvalue(),
            )
        finally:
            sys.stdout = old_stdout


# =============================================================================
# ToolRegistry
# =============================================================================

class ToolRegistry:
    """Registry for tools available to the agent."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        """Retrieve a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[Tool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def get_tool_descriptions(self) -> List[Dict[str, Any]]:
        """Return a list of tool descriptions in OpenAI function format."""
        return [tool.to_openai_function() for tool in self._tools.values()]


# =============================================================================
# AskQuestionUseCase (ReAct Agent)
# =============================================================================

class AskQuestionUseCase:
    """
    ReAct agent that answers a question using tools.
    It iteratively asks the LLM for the next step (tool call or answer),
    executes the tool, and accumulates results until an answer is given.
    """

    def __init__(
        self,
        llm: LlmPort,
        registry: ToolRegistry,
        schema_repo: SchemaRepository,
        max_iterations: int = 10,
    ):
        self._llm = llm
        self._registry = registry
        self._schema_repo = schema_repo
        self._max_iter = max_iterations

    def ask(self, question: str) -> AgentSession:
        session = AgentSession(question=question)
        session.history.append(AgentTurn(role="user", content=question))

        schema = self._schema_repo.load_schema()
        log.debug("Schema loaded: %s", schema.table_names())

        # Conversation history for LLM (simplified)
        lm_history: List[Dict[str, str]] = []

        while session.iterations < self._max_iter:
            session.iterations += 1
            log.debug("Iteration %d/%d", session.iterations, self._max_iter)

            # Get next step from LLM
            step = self._plan_next_step(question, schema, session.collected_results, lm_history)
            log.debug("Step: %s | Reasoning: %s", step.step_type, step.reasoning)

            # ANSWER branch
            if step.step_type.upper() == "ANSWER":
                session.final_answer = step.answer
                session.status = QueryStatus.SUCCESS
                session.history.append(AgentTurn(role="assistant", content=step.answer))
                log.debug("Final answer after %d iteration(s).", session.iterations)
                return session

            # TOOL_CALL branch
            if step.step_type.upper() == "TOOL_CALL":
                tool_name = step.tool_name
                tool_args = step.tool_args
                if not tool_name:
                    log.warning("No tool name provided in TOOL_CALL step.")
                    session.status = QueryStatus.VALIDATION_ERROR
                    session.final_answer = "No tool specified. Please rephrase."
                    return session

                # Retrieve tool
                tool = self._registry.get(tool_name)
                if not tool:
                    error_msg = f"Unknown tool: {tool_name}"
                    log.warning(error_msg)
                    session.history.append(AgentTurn(role="tool_result", content=error_msg))
                    lm_history.append({"role": "user", "content": error_msg})
                    session.status = QueryStatus.EXECUTION_ERROR
                    continue

                # Log the tool call
                session.history.append(
                    AgentTurn(
                        role="assistant",
                        content=f"[REASONING] {step.reasoning}\n[TOOL] {tool_name} {tool_args}",
                    )
                )
                lm_history.append({"role": "assistant", "content": f"[TOOL] {tool_name} {tool_args}"})

                # Execute tool
                try:
                    result = tool.execute(**tool_args)
                except Exception as exc:
                    error_msg = f"Tool execution error: {exc}"
                    log.warning(error_msg)
                    session.history.append(AgentTurn(role="tool_result", content=error_msg))
                    lm_history.append({"role": "user", "content": error_msg})
                    session.status = QueryStatus.EXECUTION_ERROR
                    continue

                # Store result
                session.collected_results.append(result)
                if result.success:
                    session.status = QueryStatus.SUCCESS
                else:
                    session.status = QueryStatus.EXECUTION_ERROR

                # Provide result summary to LLM
                result_summary = f"[RESULT for {tool_name}]\n{result.as_text_table()}"
                session.history.append(AgentTurn(role="tool_result", content=result_summary))
                lm_history.append({"role": "user", "content": result_summary})

                # If tool failed, we could try to fix by re-planning (but we continue loop)
                continue

            # Unknown step type
            log.warning("Unknown step type: %s", step.step_type)
            session.status = QueryStatus.VALIDATION_ERROR
            session.final_answer = "Invalid step type. Please try again."
            return session

        # Iteration limit reached
        session.status = QueryStatus.ITERATION_LIMIT
        session.final_answer = (
            f"Could not answer the question after {self._max_iter} attempts. "
            "Try rephrasing or simplifying the question."
        )
        return session

    def _plan_next_step(
        self,
        question: str,
        schema: Any,
        collected_results: List[ToolResult],
        history: List[Dict[str, str]],
    ) -> AgentStep:
        """
        Ask the LLM for the next step. The LLM is expected to return a JSON
        with fields: step_type ("ANSWER" or "TOOL_CALL"), reasoning,
        answer (if ANSWER), tool_name and tool_args (if TOOL_CALL).
        """
        # Build system prompt with tool descriptions and schema
        tools_desc = self._registry.get_tool_descriptions()
        tool_info = json.dumps(tools_desc, indent=2)
        schema_str = str(schema)  # adjust to actual schema representation

        system_msg = (
            "You are an AI assistant that answers questions by using tools. "
            "You have access to the following tools:\n"
            f"{tool_info}\n\n"
            "Database schema:\n"
            f"{schema_str}\n\n"
            "You must respond in JSON format with the following fields:\n"
            "- step_type: either 'ANSWER' or 'TOOL_CALL'\n"
            "- reasoning: brief explanation of why you chose this step\n"
            "- If ANSWER: provide 'answer' field with the final answer\n"
            "- If TOOL_CALL: provide 'tool_name' (string) and 'tool_args' (object) matching the tool's parameters.\n\n"
            "Do not output anything else."
        )

        # Build history for LLM (we need to combine question, previous turns)
        # We'll convert session history to a list of messages.
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": f"Question: {question}"},
        ]
        # Add previous interactions (history is list of {"role": "user" or "assistant", "content": ...})
        for turn in history:
            messages.append(turn)

        # Call LLM (assuming LlmPort has a method to generate with messages)
        # Since we don't know the exact interface, we'll assume there is a method
        # generate(prompt: str) or similar. We'll use a generic approach.
        # We'll use the existing LlmPort's plan_next_step? But that's specific to SQL.
        # We'll create a new method in the port interface? For now, we'll assume
        # the LLM can take a prompt and return text. We'll implement a simple
        # method using the LLM to get a response and parse JSON.
        # We'll call self._llm.plan_next_step but that expects question, schema, collected_results, history.
        # Instead, we'll use a more generic method if available, or we can use the LLM directly.
        # Since we have a LlmPort, we can extend it or use a workaround.
        # For this example, we'll assume LlmPort has a method `generate(prompt: str) -> str`.
        # If not, we'll adapt.
        # We'll add a method `generate` to LlmPort in our implementation.

        # We'll use a placeholder. In practice, you'd implement an adapter.
        # For now, we'll call a method that we assume exists: self._llm.generate(messages)
        # But to keep code self-contained, we'll create a stub method that uses
        # the existing plan_next_step but we'll simulate by constructing a prompt.
        # Actually, we can use the LlmPort's plan_next_step if we adapt the signature.
        # Since we are rewriting the code, we can define a new interface for the LLM.
        # I'll define an AgentLlmPort that has a method `plan_next_step`.
        # But to avoid changing existing code, we'll keep using LlmPort but
        # we'll add a method `generate` to the interface (not ideal).
        # For this file, we'll assume the LlmPort has a method `generate(prompt: str) -> str`.

        # We'll use the system message and conversation history to build a prompt.
        prompt = system_msg + "\n\n" + " ".join([f"{m['role']}: {m['content']}" for m in messages])

        # Call LLM
        response = self._llm.generate(prompt)  # assuming this exists

        # Parse JSON
        try:
            # Extract JSON from response (might be surrounded by text)
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if not json_match:
                raise ValueError("No JSON object found in response.")
            data = json.loads(json_match.group())
            step_type = data.get("step_type", "").upper()
            reasoning = data.get("reasoning", "")
            answer = data.get("answer") if step_type == "ANSWER" else None
            tool_name = data.get("tool_name") if step_type == "TOOL_CALL" else None
            tool_args = data.get("tool_args", {}) if step_type == "TOOL_CALL" else {}
            return AgentStep(
                step_type=step_type,
                reasoning=reasoning,
                answer=answer,
                tool_name=tool_name,
                tool_args=tool_args,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            log.error("Failed to parse LLM response: %s", exc)
            # Fallback: treat as answer
            return AgentStep(
                step_type="ANSWER",
                reasoning="Failed to parse LLM response, returning as answer.",
                answer=response,
            )


# =============================================================================
# Example Usage
# =============================================================================

if __name__ == "__main__":
    # This is a mock example. In real usage, you would provide concrete implementations
    # of LlmPort, QueryExecutor, SchemaRepository, etc.

    class MockLlmPort(LlmPort):
        def generate(self, prompt: str) -> str:
            # Simple mock: returns a hardcoded step or answer
            if "SELECT" in prompt:
                return json.dumps({
                    "step_type": "TOOL_CALL",
                    "reasoning": "I need to fetch employee data.",
                    "tool_name": "sql",
                    "tool_args": {"sql": "SELECT * FROM employees LIMIT 5"},
                })
            else:
                return json.dumps({
                    "step_type": "ANSWER",
                    "reasoning": "I have enough data.",
                    "answer": "The employees are John, Mary, and Bob.",
                })

    class MockQueryExecutor(QueryExecutor):
        def execute(self, sql: str):
            # Mock result
            class Result:
                rows = [{"name": "John"}, {"name": "Mary"}]
                truncated = False
            return Result()

    class MockSchemaRepository(SchemaRepository):
        def load_schema(self):
            class Schema:
                def table_names(self):
                    return ["employees"]
                def __str__(self):
                    return "Table: employees (id, name, role)"
            return Schema()

    # Setup
    llm = MockLlmPort()
    query_exec = MockQueryExecutor()
    schema_repo = MockSchemaRepository()
    registry = ToolRegistry()
    registry.register(SqlTool(query_exec, schema_repo))
    registry.register(PythonTool())

    use_case = AskQuestionUseCase(llm, registry, schema_repo, max_iterations=3)

    # Run
    session = use_case.ask("List all employees.")
    print(f"Final answer: {session.final_answer}")
    print(f"Status: {session.status}")
    for turn in session.history:
        print(f"{turn.role}: {turn.content[:100]}...")