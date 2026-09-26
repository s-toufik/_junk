# agent-orchestrator — the two engines compared

Personal reference, written 2026-09-26. Side by side: `AGENT_ENGINE=langgraph`
(`readme_interne.md`, §7, §8, §16) and `AGENT_ENGINE=anthropic_sdk`
(`readme_interne_anthropic_sdk.md`). Same rules, same API, different machinery.

---

## Contents

1. [Where the two engines split](#1-where-the-two-engines-split)
2. [The same route, drawn twice](#2-the-same-route-drawn-twice)
3. [Step-by-step equivalence](#3-step-by-step-equivalence)
4. [Scenario by scenario](#4-scenario-by-scenario)
5. [What the UI receives](#5-what-the-ui-receives)
6. [Differences that matter](#6-differences-that-matter)
7. [Which one to run](#7-which-one-to-run)
8. [Shared nomenclature](#8-shared-nomenclature)

---

## 1. Where the two engines split

Everything down to `AgentPort.stream()` is shared. The engines are two implementations of
that one port.

```
             homelab-ui ── POST /v1/stream ──▶ controller ──▶ use case
                                                                │
                                                 AgentPort.stream(request)
                                                                │
                         ┌──────────── AGENT_ENGINE ────────────┴─────────────┐
                         ▼                                                      ▼
              LangGraphAgent (langgraph)                                  AnthropicSdkAgent (anthropic_sdk)
              ───────────────────────                                ─────────────────────────
              one compiled graph per model                           Claude Code CLI subprocess
              our code runs every step                               per live conversation;
              (nodes + router)                                       the CLI runs the loop,
                                                                     we steer it with callbacks
                         │                                                      │
              LangChain ChatOpenAI                                   LiteLLM gateway
              ── OpenAI chat/completions ──▶ llama.cpp ◀── OpenAI ── (Anthropic → OpenAI)
                         │                                                      │
              ToolRegistry + McpTool                                 CLI talks MCP directly
              (discovered at boot)                                   (connects every turn)
                         │                                                      │
              checkpointer: MongoDB → SQLite                         MongoDB only:
              (whole AgentState)                                     conversations + sessions
```

Both yield the same domain events (`status`, `token`, `reset`, `final`), and the use case
cannot tell them apart.

---

## 2. The same route, drawn twice

### LangGraph: the route is a graph we wrote

```
ingest ─▶ context ─┬─▶ clarify ─────────────────────────────────────────┐
                   ├─▶ plan ───────────────────────────────────────────┤
                   └─▶ act ◀──▶ tools                                   ▼
                        ├─▶ reflect ─┬─▶ feedback ─▶ act            finalize ─▶ summarize ─▶ END
                        │            └─▶ finalize
                        └─▶ finalize   (direct & no tools · or budget spent)
```

Every arrow is an edge in `agent_graph.py`; every branch is a function in `agent_router.py`.

### SDK: the route is a loop we steer

```
ingest ─▶ context ─▶ mode ──┬─ CLARIFY ─▶ ClarifyStep (no LLM) ─────────────────────┐
                           ├─ PLAN ────▶ PlanStep (1 planner call) ───────────────┤
                           ├─ DIRECT ──┬──▶ query ─▶ ┌──── the CLI's loop ─────┐   │
                           └─ EXECUTE ─┘             │ model ─▶ tool? ─▶ rules │   │
                                                     │   ▲          ─▶ tool ─┐ │   │
                                                     │   └───────────────────┘ │   │
                                                     │ Stop hook ─▶ reflect    │   │
                                                     │   retry ─▶ back to model│   │
                                                     └────────────┬────────────┘   │
                                                                  ▼                ▼
                                                     finalize ─▶ summarize ─▶ save ─▶ final
```

Same branches as the graph: clarify and plan never start the CLI, exactly like `ClarifyNode`
and `PlanNode`. Only DIRECT and EXECUTE run the CLI's loop, and only EXECUTE connects the
tools. The loop itself belongs to the CLI; it calls back into `ToolsStep`, `ReflectStep` and
`FeedbackStep`.

---

## 3. Step-by-step equivalence

Every step has a class in both engines: a node in LangGraph, a step in the SDK engine.

| Step | LangGraph | Anthropic SDK |
|---|---|---|
| ingest | `IngestNode`: stamps limits, records the user message (`LangGraphAgent` loads the checkpoint) | `IngestStep`: loads the `AgentState` from Mongo |
| context | `ContextNode`: context LLM + `_resolve` (mode rules); routed by `AgentRouter.after_context` | `ContextStep`: context LLM + `_resolve` (same rules) → `TurnState` with its mode |
| clarify | `ClarifyNode`: the answer **is** the question, no model call | `ClarifyStep`: the same, no CLI and no model call |
| plan | `PlanNode`: the planner LLM writes the plan as text | `PlanStep`: the same planner call and prompt, outside the CLI |
| act | `ActNode`: one planner LLM call; tools **bound** only after approval | `ActStep`: the same system prompt shape, then the CLI's whole loop; tools **connected** only after approval |
| tools | `ToolsNode`: runs the MCP calls (concurrently) | `ToolsStep`: **which tools exist and which native rules allow them** per mode (the CLI runs and enforces them) |
| reflect | `ReflectNode`, routed by `after_act` (skip rule in the router) | `ReflectStep`, called by the Stop hook (skip rule in `applies()`) |
| feedback | `FeedbackNode`: critique into the scratch → back to `act` | `FeedbackStep`: blocks the stop with the critique → the CLI continues |
| finalize | `FinalizeNode._settle`: answer, outcome, transcript | `FinalizeStep._settle`: answer, outcome, exchange, SDK session id |
| summarize | `SummarizeNode`: LLM summary of old turns (and `ContextWindow` trimming) | `SummarizeStep`: keeps the last 10 exchanges (the CLI compacts the model's context) |
| budget | `max_iterations` act steps (`after_act`) | `max_turns` (the CLI stops, `error_max_turns`) |
| save | LangGraph checkpoint (`thread_id = request_id`) | `AgentStateStorePort` (Mongo) + session entries in Mongo |
| final event | `LangGraphAgent` yields `final` from the end state | `AnthropicSdkAgent` emits `final` after saving |

How the steps are wired:

| | LangGraph | Anthropic SDK |
|---|---|---|
| Who orders the steps | the graph edges + `AgentRouter` | `AnthropicSdkAgent._turn` (straight line) + the CLI's loop |
| How they are assembled | `build_agent` → `AgentGraph(ingest=…, context=…, …)` | `AnthropicSdkDI` → `AgentSteps(ingest=…, context=…, …)` → `AnthropicSdkAgent(steps=…)` |
| Per-request state | `AgentState` + `TurnState` in the graph state | `AgentState` + `TurnState` passed to each step |

---

## 4. Scenario by scenario

LLM calls count every model request, including the side calls (context,
reflection). "Tool round" = one model call that asks for tools.

| Scenario | LangGraph route | calls | SDK route | calls |
|---|---|---|---|---|
| "hello" (direct) | context → act → finalize | **2** | context → DIRECT → 1 model call, reflection skipped | **2** |
| task → plan | context → plan → finalize | **2** | context → plan → finalize (no CLI) | **2** |
| "yes", one tool | context → act(tool) → tools → act → reflect → finalize | **4** | context → EXECUTE → model(tool) → tool → model → Stop hook reflects | **4** |
| continuation | context → act → reflect → finalize | **3** | context → DIRECT → model → Stop hook reflects | **3** |
| one retry | + feedback → act → reflect | **+2** | + hook blocks → model → reflect | **+2** |
| ambiguous | context → clarify → finalize | **1** | context → clarify → finalize (no CLI) | **1** |
| plan revision | context → plan (previous plan in the prompt) | **2** | context → plan (previous plan in the prompt) | **2** |
| budget spent | act at `max_iterations` with tool calls → finalize | — | CLI stops at `max_turns` → `FinalizeStep` | — |
| long conversation | + summarize once over half the context budget | +1 | handled inside the CLI | — |

Outcomes are identical in both: `answered`, `best_effort`, `budget_exhausted`,
`awaiting_approval`, `clarification`, in the same `final.metadata`
(`iteration`, `max_iteration`, `outcome`).

---

## 5. What the UI receives

Same scenario — "yes" to a pending plan, one tool, accepted — on each engine:

```
LangGraph                                  Anthropic SDK
─────────                                  ─────────────
status  Understanding your request         status  Understanding your request
status  Running file_reader                [token … reset]      (only if a preamble)
status  Checking the answer                status  Running file_reader
token   <the whole answer, once>           token · token · token …   (live)
final   outcome=answered                   status  Checking the answer
complete                                   final   outcome=answered
                                           complete
```

With a retry:

```
LangGraph                                  Anthropic SDK
─────────                                  ─────────────
status  Checking the answer                token … (draft A, live)
status  Checking the answer                status  Checking the answer
token   <final answer, once>               reset
final   outcome=answered                   status  Improving the answer
                                           token … (draft B, live)
                                           status  Checking the answer
                                           final   outcome=answered
```

| | LangGraph | Anthropic SDK |
|---|---|---|
| When text appears | at the end, all at once | as the model writes it |
| Rejected drafts visible | never | briefly, then `reset` |
| `reset` events | never sent | preamble before a tool, rejected draft, answer replaced at settle |
| `status` events | context, plan, tools, reflect | context, plan, each allowed tool, reflect, retry |

The UI handles both with one contract: append `token`, clear on `reset`, show `status` beside
the bubble, replace the bubble with `final.content`.

---

## 6. Differences that matter

| Topic | LangGraph | Anthropic SDK |
|---|---|---|
| **Who runs the loop** | our code: every step is a node, every branch a router function | the CLI; we act through callbacks |
| **Determinism / debugging** | high: the path is in the graph, the state in the checkpoint | lower: the CLI's internal steps are a black box between our callbacks |
| **Plan enforcement** | tools not bound → the model cannot even call them | the same: built-in tools off and MCP servers not connected before approval; after it, the CLI's own rules (`dontAsk`) |
| **Plan capture** | the planner's text is the plan | the same (one planner call outside the CLI) |
| **Streaming** | one `token` with the accepted answer | live tokens + `reset` |
| **Model protocol** | OpenAI chat/completions, direct | Anthropic Messages → LiteLLM → OpenAI |
| **Extra processes** | none | 1 LiteLLM gateway + 1 CLI subprocess per live conversation |
| **Concurrency cost** | light: coroutines sharing one graph | heavier: a process per conversation; keep `MAX_CONCURRENT_STREAMS` low |
| **Memory storage** | whole state as one checkpoint; MongoDB, SQLite fallback | conversation doc + one document per transcript entry; MongoDB required |
| **Context size control** | ours: `ContextWindow` + summary node | the CLI's; its prompt additions and compaction are not ours |
| **Tool discovery** | once at boot (a server back later needs a restart) | the catalog in the prompts: once at boot, like LangGraph; the CLI still connects to the servers on every EXECUTE turn |
| **Model settings** | `ChatOpenAI(max_tokens, temperature, reasoning_effort)` + `ContextWindow` | CLI env (`CLAUDE_CODE_MAX_CONTEXT_TOKENS`, `…_MAX_OUTPUT_TOKENS`), `effort`/`thinking`, temperature in LiteLLM, `extra_body` for side calls |
| **Prompt overhead** | only our prompts | our prompt + the CLI's header, environment block, token notes |
| **Chat templates** | one system message at the start | also `system` messages mid-conversation (check non-Qwen models) |
| **Retry granularity** | reflection sees the draft in the scratch; feedback node | reflection in the Stop hook; critique becomes the hook's reason |
| **Clarify** | no model call | no model call |
| **Tests** | real compiled graph + scripted LLMs | scripted `query()` driving the real callbacks + real CLI smoke test |
| **Removing a dependency later** | — | LiteLLM: `LITELLM_ENABLED=false` + `ANTHROPIC_BASE_URL` |

---

## 7. Which one to run

- **LangGraph** when you want to see and control every step, the lightest runtime, and the
  guarantee that only accepted answers are shown. It is the engine that has run on your
  real models.
- **Anthropic SDK** when you want live streaming, the Claude Code harness (its context
  handling, and later its subagents and skills), and you accept a subprocess per
  conversation. It still needs the checks listed in `readme_interne_anthropic_sdk.md` §15
  against `sirius`.

Switching is one variable: `AGENT_ENGINE`. Both use the same models (`llm.yml`), the same MCP
servers, the same API and the same UI contract.

---

## 8. Shared nomenclature

Both adapters use one vocabulary, so the same concept has the same name, file and folder
in each. The rule:

- **Components that execute a step are named after the step**, with the same labels in both
  engines: `context`, `plan`, `act`, `tools`, `reflect`, `feedback`, `finalize`, `summarize`.
  LangGraph: `node/<step>_node.py` → `<Step>Node`. SDK: `step/<step>_step.py` → `<Step>Step`.
- **Data and prompts are named after the concept**: `TurnContext`, `ReflectionDecision`,
  `context_prompt`, `reflection_prompt`…
- **Same folders**: `enum/`, `schema/`, `prompt/`, `service/`, `port/` (the engine's own
  interfaces, Protocols only), `store/` (what is saved and how); the adapter entry point is
  `<Engine>Agent` in `<engine>_agent.py`.

| Concept | LangGraph adapter | Anthropic SDK adapter |
|---|---|---|
| Adapter entry (`AgentPort`) | `langgraph_agent.py` · `LangGraphAgent` | `anthropic_sdk_agent.py` · `AnthropicSdkAgent` |
| All the steps together | `agent_graph.py` · `AgentGraph` | `step/agent_steps.py` · `AgentSteps` |
| Step: ingest | `node/ingest_node.py` · `IngestNode` | `step/ingest_step.py` · `IngestStep` |
| Step: context | `node/context_node.py` · `ContextNode` | `step/context_step.py` · `ContextStep` |
| Step: clarify | `node/clarify_node.py` · `ClarifyNode` | `step/clarify_step.py` · `ClarifyStep` |
| Step: plan | `node/plan_node.py` · `PlanNode` | `step/plan_step.py` · `PlanStep` |
| Step: act | `node/act_node.py` · `ActNode` | `step/act_step.py` · `ActStep` |
| Step: tools | `node/tools_node.py` · `ToolsNode` | `step/tools_step.py` · `ToolsStep` |
| Step: reflect | `node/reflect_node.py` · `ReflectNode` | `step/reflect_step.py` · `ReflectStep` |
| Step: feedback | `node/feedback_node.py` · `FeedbackNode` | `step/feedback_step.py` · `FeedbackStep` |
| Step: finalize | `node/finalize_node.py` · `FinalizeNode` | `step/finalize_step.py` · `FinalizeStep` |
| Step: summarize | `node/summarize_node.py` · `SummarizeNode` | `step/summarize_step.py` · `SummarizeStep` |
| Intent of a message | `enum/intent.py` · `Intent` | `enum/intent.py` · `Intent` |
| How a turn ended | `enum/turn_outcome.py` · `TurnOutcome` | `enum/turn_outcome.py` · `TurnOutcome` |
| Reflection verdict | `enum/reflection_action.py` · `ReflectionAction` + `schema/reflection_decision.py` · `ReflectionDecision` | same files, same classes |
| What the message means | `schema/turn_context.py` · `TurnContext` | `schema/turn_context.py` · `TurnContext` |
| A plan | `schema/plan.py` · `Plan(task, steps)` | `schema/plan.py` · `Plan(task, steps)` |
| Limits | `schema/agent_limits.py` · `AgentLimits(max_iterations, max_retries)` | same (inside `ModelProfile`) |
| Saved across turns | `store/agent_state.py` · `AgentState` | `store/agent_state.py` · `AgentState` |
| The engine's own interfaces | `port/node_port.py` · `NodePort` | `port/agent_state_store_port.py` · `AgentStateStorePort`, `port/query_port.py` · `QueryPort` |
| Persistence | `store/`: `AgentState`, `GraphState`, `state_serialization` (the checkpointer is LangGraph's) | `store/`: `AgentState`, `Exchange`, `MongoAgentStateStore`, `MongoSessionStore` |
| One request's state | `schema/turn_state.py` · `TurnState` | `schema/turn_state.py` · `TurnState` (+ `mode`, `draft`, `evidence`) |
| Prompts | `prompt/context_prompt.py`, `plan_prompt.py`, `act_prompt.py`, `reflection_prompt.py` | same modules; same `context_*`, `reflection_*`, `act_system_prompt`, `act_feedback`, `plan_approval_message` |
| JSON from an LLM | `service/structured_output.py` · `invoke_structured(llm, schema, messages)` | `service/structured_output.py` · `StructuredOutput.invoke_structured(model, system, prompt, schema)` |
| Fallback answers | `NO_ANSWER`, `BUDGET_EXHAUSTED` (`finalize_node.py`) | `NO_ANSWER`, `BUDGET_EXHAUSTED` (`finalize_step.py`) |

Names that exist in only one engine are the ones with no equivalent: LangGraph's graph
machinery (`AgentRouter`, `GraphState`, `ContextWindow`, `Conversation`, `Role`), and the
SDK's harness pieces (`TurnMode`, `TurnControls`, `OptionsFactory`, `EventChannel`,
`MongoSessionStore`, `ModelProfile`, `McpServer`, `SdkSettings`).

