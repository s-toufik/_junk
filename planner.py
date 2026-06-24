"""
agent/planner.py
================
PlannerNode: the only node that talks to the LLM.

Responsibilities (strictly one):
  - Build the message list for llm.generate()
  - Parse the raw string response into a typed AgentDecision via Pydantic
  - Write that decision into state["decision"]
  - Append the assistant message to state["messages"]

Parsing contract:
  - llm.generate() returns a raw string
  - The prompt (prompts.py) instructs the LLM to output only a JSON object
    matching the AgentDecision schema
  - Pydantic parses and validates that JSON in one call — no regex, no manual
    field extraction
  - On parse failure the node returns an AnswerDecision fallback so the graph
    always terminates cleanly

This node does NOT:
  - Execute tools
  - Make routing decisions
  - Know anything about the graph structure
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import TypeAdapter, ValidationError

from agent.prompts import build_system_prompt
from agent.state import AgentState
from application.port.outbound.ports import LlmPort
from domain.model import AgentDecision, AnswerDecision, QueryStatus

log = logging.getLogger(__name__)

# One TypeAdapter instance, reused across all calls
_decision_adapter: TypeAdapter[AgentDecision] = TypeAdapter(AgentDecision)


class PlannerNode:
    """
    Calls llm.generate(), parses the response into a typed AgentDecision,
    and writes it into state. Single responsibility: LLM interaction + parsing.
    """

    def __init__(self, llm: LlmPort) -> None:
        self._llm = llm

    def __call__(self, state: AgentState) -> dict[str, Any]:
        system   = build_system_prompt(
            tool_schemas=state["tool_schemas"],
            schema=state["schema"],
        )
        messages = [{"role": "system", "content": system}, *state["messages"]]

        raw = self._llm.generate(messages)
        log.debug("LLM raw response: %s", raw)

        decision, status = self._parse(raw)
        log.debug("Decision: %s | reasoning: %s", decision.step_type, decision.reasoning)

        return {
            "decision": decision,
            "messages": [{"role": "assistant", "content": decision.model_dump_json()}],
            **({"status": status} if status else {}),
        }

    @staticmethod
    def _parse(raw: str) -> tuple[AgentDecision, QueryStatus | None]:
        """
        Parse raw LLM output into a typed AgentDecision.

        The LLM is instructed to output only a JSON object.
        Pydantic validates structure and types in one pass.
        Returns (decision, error_status) where error_status is set only on failure.
        """
        try:
            data     = json.loads(raw.strip())
            decision = _decision_adapter.validate_python(data)
            return decision, None

        except json.JSONDecodeError as exc:
            log.error("LLM response is not valid JSON: %s | raw=%r", exc, raw)
        except ValidationError as exc:
            log.error("LLM JSON does not match AgentDecision schema: %s", exc)

        fallback = AnswerDecision(
            reasoning="LLM output could not be parsed into a valid decision.",
            answer="I encountered an internal error and cannot complete this request.",
        )
        return fallback, QueryStatus.PARSE_ERROR
