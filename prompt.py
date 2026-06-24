"""
agent/prompts.py
================
System prompt for the ReAct planner.

The prompt embeds the exact JSON schema the LLM must follow so that
llm.generate() output can be parsed deterministically by Pydantic.
No regex. No free-text extraction. The schema is derived directly from
the Pydantic models to stay in sync with the domain automatically.
"""

from __future__ import annotations

import json

from pydantic import TypeAdapter

from domain.model import AgentDecision


# Derive the JSON schema from the Pydantic union once at import time.
# This guarantees the prompt schema is always in sync with the domain model.
_DECISION_SCHEMA: str = json.dumps(
    TypeAdapter(AgentDecision).json_schema(),
    indent=2,
)

_SYSTEM_PROMPT = """\
You are a precise data analyst assistant. Answer the user's question by \
reasoning step by step and calling tools when needed.

## Available tools
{tool_schemas}

## Database schema
{schema}

## Output format — STRICT
You must reply with a single JSON object that exactly matches this schema.
Do not include markdown fences, prose, or any text outside the JSON object.

{decision_schema}

Rules:
- Set "step_type" to "TOOL_CALL" if you need to invoke a tool.
- Set "step_type" to "ANSWER" when you have enough information to answer.
- "reasoning" must always be present and non-empty.
- For TOOL_CALL, "tool_name" must be one of the available tool names above \
  and "tool_args" must match that tool's parameter schema exactly.
- For ANSWER, "answer" must be a complete, user-facing response.
- Call a tool only when you need data you do not yet have.
"""


def build_system_prompt(tool_schemas: str, schema: str) -> str:
    return _SYSTEM_PROMPT.format(
        tool_schemas=tool_schemas,
        schema=schema,
        decision_schema=_DECISION_SCHEMA,
    )
