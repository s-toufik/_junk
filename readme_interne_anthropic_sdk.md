# agent-orchestrator — internal guide: the Anthropic SDK engine

Personal reference, written 2026-09-26. This file covers the second engine,
`AGENT_ENGINE=anthropic_sdk`. Everything the two engines share (API, ports, SSE contract,
configuration, boot, MCP connectors) is in `readme_interne.md`. The route-by-route
comparison with the LangGraph engine is in `readme_interne_engines_comparison.md`.

Code: `src/agent_orchestrator/adapter/outbound/anthropic_sdk/`,
`src/agent_orchestrator/adapter/outbound/llm/lite_llm/`, wiring in
`src/bootstrap/di/anthropic_sdk_di.py`.

---

## Contents

1. [The idea in one paragraph](#1-the-idea-in-one-paragraph)
2. [The picture: processes and connections](#2-the-picture-processes-and-connections)
3. [One request, on a timeline](#3-one-request-on-a-timeline)
4. [The route map: from a message to an outcome](#4-the-route-map-from-a-message-to-an-outcome)
5. [Route traces, scenario by scenario](#5-route-traces-scenario-by-scenario)
6. [The steps, and how the agent is composed](#6-the-steps-and-how-the-agent-is-composed)
7. [Modes](#7-modes)
8. [Controls: permission gate, plan tool, Stop hook](#8-controls-permission-gate-plan-tool-stop-hook)
9. [Options passed to the SDK](#9-options-passed-to-the-sdk)
10. [Storage](#10-storage)
11. [LiteLLM gateway](#11-litellm-gateway)
12. [Boot and configuration](#12-boot-and-configuration)
13. [Errors](#13-errors)
14. [Tests](#14-tests)
15. [Verified, and still to verify](#15-verified-and-still-to-verify)

---

## 1. The idea in one paragraph

The Claude Agent SDK is the Claude Code harness packaged as a library. Each call to
`query(prompt, options)` starts the Claude Code **CLI as a subprocess**, and the CLI runs the
agent loop itself: call the model, run tools, feed the results back, stop. We don't write that
loop. We steer it from outside with three things: the **options** (which tools exist, the
system prompt, the session to resume), a **permission callback** (which tool calls are
allowed) and **hooks** (what happens when the model wants to stop). Around the SDK run we add
one context step (an LLM call) before, and the storage of the turn after.

---

## 2. The picture: processes and connections

```
┌────────────┐  POST /v1/stream   ┌──────────────────────── agent process (FastAPI) ─────────────────────────┐
│ homelab-ui │ ─────────────────▶ │ controller → use case → AnthropicSdkAgent.stream()                                 │
│            │ ◀── SSE events ─── │                           │                                               │
└────────────┘                    │   ┌───────────────────────┴───────────┐                                   │
                                  │   │ Context / Plan / ReflectStep      │── Anthropic Messages ──┐         │
                                  │   │ (anthropic SDK, StructuredOutput)    │                        │         │
                                  │   └────────────────────────────────────┘                        │         │
                                  │   ┌────────────────────────────────────┐                        │         │
                                  │   │ TurnControls (in-process callbacks)│◀── control protocol ─┐ │         │
                                  │   │  PreToolUse · Stop hook            │    (stdin/stdout)    │ │         │
                                  │   │                                    │                      │ │         │
                                  │   └────────────────────────────────────┘                      │ │         │
                                  │   Mongo stores ◀──────────────────────────────┐               │ │         │
                                  └───────────────────────────────────────────────┼───────────────┼─┼─────────┘
                                                                                  │               │ │
                          ┌───────────────────────────────┐                       │               │ │
                          │ Claude Code CLI (subprocess)  │───────────────────────┼───────────────┘ │
                          │ one per live conversation     │── session entries ────┘                 │
                          │ runs the agent loop           │                                         │
                          └──────┬────────────────┬───────┘                                         │
                   Anthropic     │                │ MCP (HTTP)                                      │
                   Messages      │                ▼                                                 │
                                 │        ┌──────────────┐                                          │
                                 │        │ MCP toolbox  │                                          │
                                 │        └──────────────┘                                          │
                                 ▼                                                                  ▼
                          ┌──────────────────────────────┐  OpenAI chat/completions  ┌──────────────────┐
                          │ LiteLLM gateway (subprocess) │ ────────────────────────▶ │ llama.cpp        │
                          │ 127.0.0.1:4000               │ ◀──────────────────────── │ LLM_BASE_URL     │
                          └──────────────────────────────┘                           └──────────────────┘

MongoDB: agent_sdk_states (our turn state) · agent_sdk_sessions (the SDK transcript)
```

Three things to take from this picture:

- **Two kinds of LLM callers.** The CLI calls the model for the agent loop. Our own process
  calls it directly (through the same gateway) for the context, plan and reflect steps.
- **The CLI calls back into our process** before every tool call and at every Stop. That is how we keep control without owning the loop.
- **Everything the model sees goes through LiteLLM**, which turns Anthropic Messages into
  OpenAI chat/completions for llama.cpp (§11).

---

## 3. One request, on a timeline

Time flows down. "yes" to a pending plan, with one tool call, is shown because it touches
every piece.

```
 UI        steps (agent)              Mongo      ContextStep    CLI (query)        TurnControls      LiteLLM→llama.cpp   MCP
 │ POST        │                          │           │              │                 │                    │             │
 │────────────▶│ IngestStep: load ───────▶│           │              │                 │                    │             │
 │             │◀── AgentState ───────────│           │              │                 │                    │             │
 │◀─ status "Understanding your request" ─────────────│              │                 │                    │             │
 │             │ ContextStep ────────────────────────▶│ ─────────────────────────────────────────────────────▶│  LLM call 1 │
 │             │◀── intent=plan_approval ─────────────│              │                 │                    │             │
 │             │ ContextStep → EXECUTE, turn.plan      │              │                 │                    │             │
 │             │ ActStep:                              │              │                 │                    │             │
 │             │  query(prompt="yes", options) ──────────────────────▶│  load session   │                    │             │
 │             │                          │◀── entries ──────────────│                 │                    │             │
 │             │                          │           │              │ ────────────────────────────────────▶│ LLM call 2  │
 │             │                          │           │              │ wants mcp__toolbox__file_reader     │             │
 │             │                          │           │              │ PreToolUse ────▶│ ToolsStep.announce │             │
 │◀─ status "Running file_reader" ─────────────────────────────────────────────────────│                    │             │
 │             │                          │           │              │ ─────────────────────── call tool ─────────────────▶│
 │             │ UserMessage(tool result) → turn.evidence │          │◀──────────────────────────────────────── result ────│
 │             │                          │           │              │ ────────────────────────────────────▶│ LLM call 3  │
 │◀─ token · token · token … (live deltas) ────────────────────────── │                 │                    │             │
 │             │                          │           │              │ wants to stop   │                    │             │
 │             │                          │           │              │ Stop hook ─────▶│ ReflectStep.applies│             │
 │◀─ status "Checking the answer" ────────────────────────────────────────────────────│                    │             │
 │             │                          │           │              │                 │ ReflectStep ──────▶│ LLM call 4  │
 │             │                          │           │              │◀── {} (accept) ─│                    │             │
 │             │                          │◀── append entries ───────│                 │                    │             │
 │             │◀── ResultMessage(session_id, num_turns) ────────────│                 │                    │             │
 │             │ FinalizeStep → answer, outcome                       │                 │                    │             │
 │             │ SummarizeStep, save ────▶│           │              │                 │                    │             │
 │◀─ final (answer, metadata) ─│          │           │              │                 │                    │             │
 │◀─ complete (use case) ──────│          │           │              │                 │                    │             │
```

In code, the producer is `AnthropicSdkAgent._turn` (`anthropic_sdk_agent.py`), which runs the
steps in order (§6). It runs as its own task so that events
emitted by the hooks reach the UI while the SDK iterator is still waiting on the model.

---

## 4. The route map: from a message to an outcome

```
                                 user message
                                      │
                                      ▼
                      ┌───────────────────────────────┐
                      │ ContextStep  (LLM call)    │  sees: last 3 exchanges,
                      │ → intent, standalone_query,   │        pending plan,
                      │   success_criteria, question  │        latest message
                      └───────────────┬───────────────┘
                                      │ ContextStep._resolve
     ┌─────────────────┬──────────────┼──────────────────────┬─────────────────────┐
     ▼                 ▼              ▼                      ▼                     ▼
 plan_approval     task /          ambiguous             continuation /       plan_approval
 + pending plan    plan_revision   + a question          direct               but nothing pending
     │                 │              │                      │                     │
     ▼                 ▼              ▼                      ▼                     │
 ┌─────────┐      ┌─────────┐    ┌──────────┐          ┌──────────┐                │
 │ EXECUTE │      │  PLAN   │    │ CLARIFY  │          │  DIRECT  │◀───────────────┘
 └────┬────┘      └────┬────┘    └────┬─────┘          └────┬─────┘
      │                │              │                     │
 tools: MCP ✓     no CLI:         no CLI, no LLM:      tools: none, MCP
 + built-ins      PlanStep calls  the answer is the    not even connected
                  the planner     context's question   (answers from the
                  (1 LLM call)                          conversation)
      │                │              │                     │
      ▼                │              │                     ▼
   SDK run             │              │                  SDK run
      │                │              │                     │
      ▼                │              │              ┌──────┴──────────────┐
 Stop hook:            │              │              │ intent=direct and   │
 reflect ⇄ retry       │              │              │ no tool used?       │
      │                │              │              └──┬───────────────┬──┘
      │                │              │            yes  │               │ no (continuation)
      │                │              │                 ▼               ▼
      │                │              │           no reflection   Stop hook: reflect ⇄ retry
      ▼                ▼              ▼                 ▼               ▼
 answered /       awaiting_       clarification     answered       answered /
 best_effort /    approval                                          best_effort
 budget_exhausted (plan saved
                   as pending)
```

The retry loop in one picture:

```
 model finishes a draft
          │
          ▼
   Stop hook (on_stop) ──── ReflectStep.applies()? ── no ──▶ stop
          │ yes
          ▼
   retries < max_retries? ── no ──────────────────────▶ stop  (outcome best_effort if the
          │ yes                                               last verdict was a retry)
          ▼
   ReflectStep (LLM) ─ accept / unreadable / error ─────▶ stop
          │ retry
          ▼
   FeedbackStep: retries += 1, draft cleared
   SSE: reset, status "Improving the answer"
   return {"decision": "block", "reason": act_feedback(critique)}
          │
          ▼
   the CLI hands the critique to the model, which writes a new draft ──▶ (back to the top)
```

---

## 5. Route traces, scenario by scenario

Each trace shows the route, the SSE events the UI receives, and the LLM calls. `status` is
shortened to its text.

### 5.1 "hello" (direct)

```
route   context → DIRECT → SDK run (1 model call) → Stop hook: skip (direct, no tools) → final
SSE     status "Understanding your request"
        token · token · token …                     (live)
        final  outcome=answered
LLM     context + 1 = 2
```

### 5.2 "count the EQD positions" (task → plan)

```
route   context → PLAN → PlanStep: one planner call (no CLI) → its text is the plan,
        saved as pending → FinalizeStep
SSE     status "Understanding your request"
        status "Preparing a plan"
        token "## Plan … \n---\nReply **yes** to run this plan, or tell me what to change."
        final  outcome=awaiting_approval  iteration=0
LLM     context + planner = 2
Saved   pending_plan = {task: standalone_query, steps: the plan}
```

Whatever the planner writes is the plan, so a weak model cannot turn a task into an answer
that skips approval. This is the LangGraph `PlanNode`, with the same prompt.

### 5.3 "yes" (execute the approved plan)

```
route   context → EXECUTE (approved plan in the system prompt)
        → model calls MCP tool → allowed by the EXECUTE rules (native) → tool result → model answers
        → Stop hook: reflect → accept → final
SSE     status "Understanding your request"
        [token … reset]                             (only if the model wrote before the tool)
        status "Running file_reader"
        token · token …                             (the answer, live)
        status "Checking the answer"
        final  outcome=answered
LLM     context + 1 per tool round + 1 answer + reflect = 4 with one tool
Saved   pending_plan cleared
```

### 5.4 "also include FX" (revise the pending plan)

```
route   context → plan_revision → PLAN (the pending plan is kept and shown to the planner
        as "the user asked to change this previous plan") → same as 5.2 with the new plan
```

### 5.5 "explain more" (continuation, with one retry)

```
route   context → DIRECT (intent continuation) → draft A
        → Stop hook: reflect → retry → block → draft B → Stop hook: reflect → accept
SSE     status "Understanding your request"
        token … (draft A)
        status "Checking the answer"
        reset
        status "Improving the answer"
        token … (draft B)
        status "Checking the answer"
        final  outcome=answered   (best_effort if B had also been rejected)
LLM     context + 2 model calls + 2 reflections = 5
```

### 5.6 "the numbers" (ambiguous)

```
route   context → CLARIFY → ClarifyStep: the answer is the context's question (no CLI, no LLM)
SSE     status · token (the question, once) · final  outcome=clarification  iteration=0
LLM     context = 1
```

### 5.7 A task that runs out of turns

```
route   EXECUTE → tool, tool, tool … → the CLI stops at max_turns (ResultMessage error_max_turns)
SSE     … status "Running …" (each tool) …
        the draft so far, or: reset + token "I reached the step limit…"
        final  outcome=budget_exhausted
```

### 5.8 A tool the model is not allowed to use yet

```
route   DIRECT → no MCP server is connected and no built-in tool exists: the model is offered
        no tool at all, so even a model that ignores the prompt cannot call one
SSE     no "Running …" status

In EXECUTE, a call outside the rules (a built-in tool outside the working directory) is
refused by the CLI (dontAsk); the refusal comes back to the model as the tool result.
```

---

## 6. The steps, and how the agent is composed

Every step of a turn is its own class in `step/`, named like the LangGraph node that does the
same job (`context` ↔ `ContextNode`, `reflect` ↔ `ReflectNode`, …). The steps keep no state:
everything about the current request lives in `TurnState`, so one set of steps serves every
user.

| Step | Class | Responsibility | Called by |
|---|---|---|---|
| ingest | `IngestStep` | load the conversation's `AgentState` (or start one) | the agent |
| context | `ContextStep` | status "Understanding…"; context LLM → `TurnContext`; resolve the mode → `TurnState` | the agent |
| clarify | `ClarifyStep` | the answer is the context's question; outcome `clarification` (no model call) | the agent |
| plan | `PlanStep` | status "Preparing a plan"; one planner call (plan prompt, tool catalog, previous plan on a revision); its text becomes the pending plan + approval message | the agent |
| act | `ActStep` | builds the system prompt (request, tool catalog, mode) and the options; runs the CLI; streams tokens, `reset` on preambles, collects tool evidence | the agent |
| tools | `ToolsStep` | the tool catalog shown to the model (`catalog`: MCP tools found at boot + built-ins), which tools exist and which rules allow them (`access`), the built-in tools section (`guidance`), status "Running <tool>" (`announce`) | `PlanStep`, `ActStep`, `TurnControls.on_pre_tool_use` |
| reflect | `ReflectStep` | `applies()` (when to judge); status "Checking…"; reflection LLM → `ReflectionDecision` | `TurnControls.on_stop` |
| feedback | `FeedbackStep` | on a retry: count it, clear the draft, `reset` + status, block the stop with `act_feedback(critique)` | `TurnControls.on_stop` |
| finalize | `FinalizeStep` | keep the answer a plan or clarify step set (sent as one token), or settle the CLI's result (budget, best effort, answered); record the exchange and the SDK session id | the agent |
| summarize | `SummarizeStep` | keep only the last 10 exchanges (the CLI compacts the model's context itself) | the agent |

`AgentSteps` (`step/agent_steps.py`) holds the ten instances. The steps depend on interfaces,
not implementations, where I/O is involved: `IngestStep` and the agent take an
`AgentStateStorePort`, `ActStep` takes a `QueryPort` (the real `claude_agent_sdk.query` by
default). `TurnControls` is not a step:
it adapts the CLI's callbacks (PreToolUse and Stop hooks) and hands each one to the right step.

### Composition

```
AnthropicSdkAgent(models, steps: AgentSteps, states, logger)
│
└─ _turn(request)
    ├─ agent_state = steps.ingest.run(request_id)
    ├─ turn        = steps.context.run(model, agent_state, message, channel)
    ├─ match turn.mode
    │    CLARIFY → steps.clarify.run(turn)                      (no CLI, no LLM)
    │    PLAN    → steps.plan.run(profile, turn, channel)       (no CLI, 1 planner call)
    │    DIRECT / EXECUTE →
    │      controls = TurnControls(turn, channel, profile,
    │                              steps.tools, steps.reflect, steps.feedback)
    │      result   = steps.act.run(turn, controls, profile, request_id, channel)
    │                  │
    │                  ├─ system prompt: request + tool catalog + EXECUTE or DIRECT section
    │                  ├─ OptionsFactory.build(…) → the CLI runs the loop
    │                  └─ the CLI calls back:
    │                       (permissions: native rules from tools.access)
    │                       PreToolUse ─▶ controls ─▶ tools.announce
    │                       Stop hook  ─▶ controls ─▶ reflect.applies → reflect.run → feedback.run
    ├─ answer, outcome = steps.finalize.run(turn, channel, result)   (result is None for plan/clarify)
    ├─ steps.summarize.run(agent_state)
    ├─ states.save(agent_state)
    └─ final event
```

The composition root is `AnthropicSdkDI._anthropic_sdk_agent`: it builds one instance of each
step (sharing `ToolsStep` between `PlanStep` and `ActStep`), bundles them
in `AgentSteps`, and gives them to the agent. Tests build the same bundle with fake I/O
(`fakes.agent_steps`).

### Files

```
anthropic_sdk/
├── anthropic_sdk_agent.py  AnthropicSdkAgent: the AgentPort; runs the steps in order
├── turn_controls.py        TurnControls: the CLI's callbacks → steps
├── options_factory.py      OptionsFactory: ClaudeAgentOptions for a turn (§9)
├── port/                   the engine's own interfaces (Protocols only):
│                           AgentStateStorePort (load/save the AgentState),
│                           QueryPort (the SDK's query(); tests inject a fake)
├── step/                   the ten steps above + agent_steps.py (AgentSteps)
├── enum/                   Intent, ReflectionAction, TurnOutcome (same as langgraph), TurnMode
├── schema/                 TurnState, TurnContext, ReflectionDecision, Plan, AgentLimits
│                           (same as langgraph); ModelProfile, McpServer, SdkSettings
├── prompt/                 context_prompt, plan_prompt, act_prompt, reflection_prompt,
│                           tool_catalog, clock (plan and act prompts: same text as langgraph)
├── service/                StructuredOutput (side calls: text or JSON), EventChannel
└── store/                  what is saved and where: AgentState, Exchange (the saved
                            document), MongoAgentStateStore (implements
                            AgentStateStorePort), MongoSessionStore (the SDK's SessionStore)

llm/lite_llm/               lite_llm_config.py, lite_llm_gateway.py (§11)
```

Per request, these objects are **new**: `EventChannel`, `TurnState`, `TurnControls`, the
options, the CLI subprocess. Shared across requests: the agent, the steps, their HTTP client,
the stores, the gateway.

---

## 7. Modes

`ContextStep._resolve` (`step/context_step.py`) turns the intent into a mode and builds the
`TurnState`. Same rules as the LangGraph engine's `ContextNode._resolve`.

| Situation | Mode | Tools | System prompt section |
|---|---|---|---|
| `plan_approval` + a pending plan | `EXECUTE` | MCP + built-in tools allowed | `EXECUTE`: the approved steps + how to work; `standalone_query = plan.task` |
| `plan_approval`, nothing pending | `DIRECT` | none | `DIRECT` (intent becomes `direct`) |
| `task`, `plan_revision`, `ambiguous` without a question | `PLAN` | — (no CLI) | the planner prompt (`PlanStep`) |
| `ambiguous` with a question | `CLARIFY` | — (no CLI, no LLM) | — |
| `continuation`, `direct` | `DIRECT` | none | `DIRECT`: answer from the conversation |

Every CLI system prompt (`act_system_prompt`) has the same shape as LangGraph's: identity,
`Request:`, the tool catalog, the mode section, the answer format, the current UTC time.

- A pending plan survives only `plan_revision` and `ambiguous`; any other intent clears it.
- `ReflectStep.applies()`: always in the CLI modes, except a `direct` intent that used no
  tools (PLAN and CLARIFY never reach the CLI).
- If the context step output can't be parsed: intent `task` → `PLAN`. Safe: nothing runs
  without approval.

---

## 8. Controls: permission gate, Stop hook

`TurnControls` (`turn_controls.py`), one per turn, receives the CLI's callbacks and hands each
one to a step.

### Native permissions — which tools exist, and what the CLI allows

Every turn runs with `permission_mode="dontAsk"`: the CLI refuses any call no rule allows.
`ActStep.access(turn)` gives the tools and rules of the turn's mode:

| Mode | Built-in tools that exist | Allow rules |
|---|---|---|
| EXECUTE | `AGENT_SDK_TOOLS` (e.g. `Glob`, `Grep`) | `<Tool>(//<WORKING_DIRECTORY>/**)` for each, `mcp__<server>__*` for each MCP server |
| DIRECT | none, and no MCP server connected | none |

- Before a plan is approved, **no tool exists** for the model: built-in tools are off and the
  MCP servers are not connected (`OptionsFactory._mcp_servers`), as LangGraph binds no tools.
  After approval, built-in tools reach only the working directory.
- Checked on the real CLI: `Glob` inside the working directory runs, outside it is refused,
  and without approval it is "no such tool".
- `Edit` needs `Read`: the CLI refuses to edit a file the model has not read. The boot refuses
  `AGENT_SDK_TOOLS` with `Edit` but no `Read`.

`TurnControls.on_pre_tool_use` (a `PreToolUse` hook) only reports progress: in EXECUTE mode
`ToolsStep.announce` sends "Running <tool>". The hook fires before the CLI checks its rules, so a
call later refused outside the working directory is also announced; its tool result says so.

When built-in tools are enabled, the EXECUTE section of the system prompt gets a part (`ToolsStep.guidance`)
naming the working directory and what each tool is for.

### `on_stop` — the Stop hook → `ReflectStep` + `FeedbackStep`

```
ReflectStep.applies(turn) and retries < max_retries?  ── no ──▶ {} (stop)
turn.reflection = ReflectStep.run(...)                 ── error / unreadable / accept ──▶ {} (stop)
retry ──▶ FeedbackStep.run(turn, decision, channel)    ──▶ {"decision": "block", "reason": act_feedback(critique)}
```

The hook timeout is 300s (`STOP_HOOK_TIMEOUT_SECONDS`) because a local reflection call can
take close to a minute. A reflect step that fails or returns unreadable JSON never blocks the
answer.

The context, plan and reflect steps call the model through `StructuredOutput`, which sends the
model's `temperature` and `reasoning_effort` in `extra_body` (the Anthropic API has no field
for them; LiteLLM forwards them to llama.cpp).

The reflect step sees (`step/reflect_step.py`): the previous exchange and the latest message
(the ground truth), the interpreted request and criteria, the approved plan, the tool results
(2000 chars each), and the draft.

---

## 9. Options passed to the SDK

`OptionsFactory.build` (`options_factory.py`):

| Option | Value | Why |
|---|---|---|
| `tools=[]` | no built-in tools | no Bash / Read / Write / Web: only your MCP tools exist |
| `setting_sources=[]`, `strict_mcp_config=True` | no settings files, no other MCP config | the server's `~/.claude` and project files are never read |
| `permission_mode="dontAsk"` + `tools` / `allowed_tools` from `ActStep.access` | only the rules of the current mode allow anything; the CLI refuses the rest | the plan approval is enforced **natively** by the CLI |
| `mcp_servers` | every MCP connector (auth headers + `X-Request-ID`), plus `planner` in PLAN mode | the model always sees your tool catalog |
| `system_prompt` | `{"type": "custom", "prompt": …, "snapshot": False}` | **`snapshot=False` is essential**: without it a resumed session keeps its first turn's system prompt and the mode never changes |
| `session_store` + `resume=session_id` | the Mongo session store | any instance can resume any conversation |
| `cwd=WORKING_DIRECTORY` | the deployment's working directory | the only place built-in tools reach, and the key sessions are stored under |
| `env` | `CLAUDE_CODE_MAX_CONTEXT_TOKENS` / `CLAUDE_CODE_MAX_OUTPUT_TOKENS` from `max_context_tokens` / `max_output_tokens` (the CLI does not know non-Claude models: without them it assumes a default window and asks for 32k output tokens), `ANTHROPIC_BASE_URL` (gateway), token, the model name for every role (`ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL`), a temporary `CLAUDE_CONFIG_DIR`, telemetry and auto-update off | the CLI never tries to reach Anthropic or a Claude model |
| `include_partial_messages=True` | token deltas | live streaming |
| `max_turns` | `max_iterations` of the model in `llm.yml` | the step budget |
| `effort` / `thinking` | `reasoning_effort` of the model; `null` → `thinking={"type": "disabled"}` | the CLI sends `reasoning_effort` to the model (it defaults to `high` otherwise); a model that does not reason gets none |
| `hooks={"Stop": …}` | `on_stop`, timeout 300s | reflection |

### Telemetry of the CLI

Two separate things:

| | Setting | Effect |
|---|---|---|
| Anthropic's reporting | `DISABLE_TELEMETRY=1`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `DISABLE_AUTOUPDATER=1` (always) | nothing leaves your network for Anthropic: no usage analytics, error reports, update checks or self-updates |
| The CLI's OpenTelemetry | `CLAUDE_CODE_ENABLE_TELEMETRY=1` + `OTEL_*` (only when `OTEL_HOST`/`OTEL_PORT` are set) | exported to **your** collector, the same one as the application (`http://<OTEL_HOST>:<OTEL_PORT>`, OTLP gRPC) |

What the collector receives per turn (checked against a local OTLP receiver):

- **Metrics:** `claude_code.token.usage`, `claude_code.cost.usage`, `claude_code.session.count`,
  `claude_code.active_time.total`.
- **Events (logs):** `claude_code.user_prompt`, `claude_code.api_request` (model, input/output
  tokens, duration), `claude_code.assistant_response`, tool events, startup events.
- **Resource attributes:** `service.name=claude-code`, `service.version`,
  `deployment.environment`, and `agent.session_id` = the conversation's `request_id`, so a turn
  can be matched with the application's traces.
- **Privacy:** prompt and response texts are sent as `<REDACTED>` (only their lengths); set
  `OTEL_LOG_USER_PROMPTS=1` on purpose if you ever want them.
- **Ignore `cost_usd` / `cost.usage`:** computed with Claude prices, meaningless for a local
  model. Token counts are real.

The CLI lives for one turn; it flushes its metrics and events when it exits (checked).

The system prompt carries the **date, not the time**, so its prefix stays the same all day
and llama.cpp can reuse its prompt cache.

What the CLI adds to what the model sees: a short header, the line "You are a Claude agent,
built on Anthropic's Claude Agent SDK.", an environment block (working directory, platform,
date) and occasional `<total_tokens>` notes, some of them as `system` messages in the
middle of the conversation (§15).

---

## 10. Storage

### `agent_sdk_states` — `MongoAgentStateStore`

One document per conversation: the `AgentState`, our own turn state.

```
{
  _id: "<request_id>",                         ← AgentState.session_id (the conversation id)
  sdk_session_id: "<SDK session uuid>",        ← passed as resume= on the next turn
  pending_plan: {task, steps} | null,
  exchanges: [{user, assistant}, …],           ← last 10; feed the context and reflect steps
  updated_at: <date>                           ← TTL index (connector ttl, 3600s)
}
```

`session_id` means the conversation id in both engines (`AgentState.session_id`). The SDK's
own transcript id is kept apart as `sdk_session_id`.

### `agent_sdk_sessions` — `MongoSessionStore`

The SDK transcript, one document per entry:

```
{ key: "<project_key>/<session_id>[/<subpath>]", batch, index, entry: "<JSON text>", updated_at }
```

- `load` returns entries sorted by `(batch, index)`: append order.
- Entries are stored as JSON text because transcripts can hold `$` or `.` field names.
- Each append refreshes `updated_at` on the whole session, so a live session never expires
  piece by piece.
- On resume, the SDK copies the session into a temporary folder and deletes it after: the
  pods keep no state on disk.

---

## 11. LiteLLM gateway

**Why.** The SDK only speaks the Anthropic Messages API (`/v1/messages`). llama.cpp is exposed
with the OpenAI convention (`/v1/chat/completions`). LiteLLM translates between them, so the
homelab keeps its OpenAI API and the agent is written as if the model server spoke Anthropic
Messages.

**Lifecycle.** Started and stopped by the agent (`AnthropicSdkDI`, then `container.stop()`):

```
boot ─▶ write the config to a temp file
     ─▶ spawn  <LITELLM_COMMAND> --config <file> --host 127.0.0.1 --port 4000
     ─▶ poll GET /health/liveliness until 200   (up to 180s; the first uvx run downloads it)
          └─ the process dies first → boot fails with its last output lines
stop ─▶ terminate, wait 10s, kill if needed, delete the temp config
```

**Config** (`lite_llm_config.py`): one entry per model of `MODEL_ALIASES`,
`hosted_vllm/<model>` with `api_base = LLM_BASE_URL` and the model's `temperature`. The CLI
never sends a temperature, so LiteLLM supplies it; without LiteLLM, set it on the llama.cpp
side (`llama-server --temp`).

> `hosted_vllm/`, not `openai/`: LiteLLM 1.102 translates `/v1/messages` for `openai/`
> models to the OpenAI **Responses** API (`/v1/responses`), which llama.cpp does not serve.
> `hosted_vllm/` keeps `/v1/chat/completions`, and streamed tool-call arguments survive the
> translation (checked).

**Not a project dependency.** `litellm[proxy]` requires `mcp<2`, which would downgrade the
app's MCP client and break it. It runs from its own environment: `uvx` locally (the default
`LITELLM_COMMAND`), a separate `/opt/litellm` venv in the Docker image.

**Removing it** (once llama.cpp's own Anthropic endpoint is used):

1. `LITELLM_ENABLED=false`, `ANTHROPIC_BASE_URL=http://sirius:8090`.
2. Optionally: delete the `litellm` stage, its `COPY` and `LITELLM_COMMAND` in the
   Dockerfile, the `llm/lite_llm` package, and its branch in
   `AnthropicSdkDI._anthropic_base_url`.

---

## 12. Boot and configuration

`AnthropicSdkDI._anthropic_sdk_agent`:

```
1. base URL     LITELLM_ENABLED → start LiteLlmGateway → http://127.0.0.1:4000
                otherwise       → ANTHROPIC_BASE_URL (required)
2. MongoDB      AsyncMongoClient from the mongodb_checkpointer connector (boot fails if down),
                collections + TTL indexes
3. side calls   AsyncAnthropic(base_url, token) → StructuredOutput → ContextStep, ReflectStep
4. settings     SdkSettings(base_url, token, working_directory, builtin_tools, MCP servers)
5. models       one ModelProfile per MODEL_ALIASES entry: name + AgentLimits(max_iterations,
                max_retries) from llm.yml; max_iterations becomes the SDK's max_turns
6. AnthropicSdkAgent(...)
```

| Variable | Default | Meaning |
|---|---|---|
| `AGENT_ENGINE` | `langgraph` | set to `anthropic_sdk` (or `make run_sdk`) |
| `MAX_CONCURRENT_STREAMS` | `200` | keep it low: one CLI process per live conversation |
| `WORKING_DIRECTORY` | `./working_directory` (resolved) | the working directory: where built-in tools can act, and the session key (same path on every instance). Mount the toolbox's working directory at the same path to share files |
| `AGENT_SDK_TOOLS` | empty | built-in tools, enabled only after a plan is approved: `Read`, `Write`, `Edit`, `Glob`, `Grep` (`Edit` needs `Read`; anything else stops the boot) |
| `LITELLM_ENABLED` | `true` | start the gateway |
| `LITELLM_COMMAND` | `uvx --from litellm[proxy]==1.102.1 litellm` | the Docker image sets `/opt/litellm/bin/litellm` |
| `LITELLM_HOST` / `LITELLM_PORT` | `127.0.0.1` / `4000` | where it listens |
| `ANTHROPIC_BASE_URL` | — | required when `LITELLM_ENABLED=false` |
| `ANTHROPIC_AUTH_TOKEN` | `none` | token sent to the gateway |

Plus the shared ones: `LLM_BASE_URL`, `TOOLBOX_URL`, `DB_MONGO_CHECKPOINT_*`.

---

## 13. Errors

| Failure | Where | Result |
|---|---|---|
| gateway unreachable, 429, 5xx during context/reflect (`anthropic` errors) | `AnthropicSdkAgent._produce` | `AgentUnavailableException` → friendly `error` event |
| SDK assistant message with `error` = `rate_limit` / `server_error` | `ActStep.run` | `AgentUnavailableException` |
| context step output unreadable | `ContextStep` | intent `task` → a plan to approve |
| reflect step unreadable or failing | `TurnControls.on_stop` | draft accepted, warning |
| `ResultMessage` `error_max_*` | `FinalizeStep` | the draft, or "I reached the step limit…"; outcome `budget_exhausted` |
| any other failed run | `FinalizeStep` | `RuntimeError` → `error` event |
| unknown `model_name` | `AnthropicSdkAgent._turn` | `ValueError` → `error` event |
| client disconnects | `stream()` | producer cancelled, CLI subprocess stopped |
| MongoDB down at boot | `AnthropicSdkDI` | boot fails (no fallback for this engine) |

---

## 14. Tests

`tests/agent_orchestrator/adapter/outbound/anthropic_sdk/`, laid out like the adapter:

| File | Covers |
|---|---|
| `fakes.py` | `FakeQuery` replaces `query()` and drives the real permission callback and Stop hook the way the CLI does; SDK message builders; `ScriptedStructuredOutput`; `MemoryAgentStates`; `turn_state()`; `agent_steps()` builds the real `AgentSteps` with fake I/O |
| `store/fake_collection.py` | a small in-memory Mongo collection |
| `test_anthropic_sdk_agent.py` | multi-turn flows through the composed agent: plan → approve → tools; tools refused before approval; retry with reset; preamble reset; budget; unstreamed answers; unknown model; outages |
| `step/test_context_step.py` | the prompt, the fallback, every mode rule, pending plan retention |
| `step/test_plan_step.py` | any planner text becomes the pending plan; the planner sees the task, the tool catalog, the conversation and the previous plan on a revision |
| `step/test_reflect_step.py` | what the judge sees, `applies()` |
| `step/test_act_step.py` | the system prompt (request, tool catalog, mode) and the tool access for each mode |
| `step/test_turn_steps.py` | ingest, clarify, tools, feedback, summarize |
| `test_turn_controls.py` | callbacks routed to the right step; the Stop hook flow |
| `test_options_factory.py` | sandboxing, MCP servers, planner only in PLAN mode, `snapshot=False`, env |
| `test_structured_output.py`, `store/test_stores.py` | JSON parsing; Mongo stores |

`tests/agent_orchestrator/adapter/outbound/llm/lite_llm/` starts a real subprocess (a fake
`litellm` script) to test the gateway: start, health, stop, crash during startup.

---

## 15. Verified, and still to verify

Verified end to end with the real CLI (2.1.283), a real LiteLLM, a real MCP server and a
scripted OpenAI-compatible model standing in for llama.cpp:

- plan → `awaiting_approval` → "yes" → tool → reflection → answer; a direct turn without
  reflection; the system prompt switching mode on every resumed turn;
- streamed tool-call arguments intact after the LiteLLM translation;
- a session saved to a `SessionStore` and resumed from it.

Still to check with your infrastructure:

1. `make run_sdk` against `sirius` (llama.cpp + MongoDB).
2. `qwen3-8b` calls the MCP tools reliably through this harness.
3. Each non-Qwen model accepts `system` messages in the middle of the conversation (the
   Mistral-family chat templates may reject them).
4. Memory per CLI process under load, to set `MAX_CONCURRENT_STREAMS`.

Known limits of this engine:

- Two requests on the same conversation at the same moment resume the same session; there is
  no lock across instances.
- The CLI is a black box between our callbacks: its prompt additions and its context
  compaction are not under our control.
