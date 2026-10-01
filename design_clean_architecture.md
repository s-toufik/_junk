# agent-orchestrator — clean architecture redesign

Status: **implemented 2026-10-01** (see `readme_interne.md` for the code as built). Differences
from the proposal below, decided while implementing:

- The MongoDB checkpointer is kept as the conversation store: there is no separate
  `ConversationRepository`; `LangGraphWorkflowRunner` loads the conversation from the thread's
  checkpoint and the graph state (`{conversation, turn}`, JSON via `TurnStateCodec`) is saved by
  the checkpointer. Steps still only see domain objects.
- `TurnEvent.entering(step)` is emitted by the runner's generic node wrapper, not by each step;
  the runner ends with `TurnEvent.finished(turn)`.
- Closing the conversation and summarising run inside the graph (`finish`, `summarize` steps), so
  the stored checkpoint holds the closed, compacted conversation.
- `AgentRequest` lives in `application/port/inbound/`; the `Summarizer` port takes the turn (the
  selected model comes from it); a `TokenCounter` port backs the summary trigger.
- Tool discovery stays at boot; the summary trigger is unchanged.

Decisions already taken:

| Decision | Choice |
|---|---|
| Claude Agent SDK engine | **dropped** (with the LiteLLM gateway, the CLI session store, the SDK state store) |
| Past conversations | **not migrated**: one new conversation store, starts empty |
| Who runs the workflow | **LangGraph**, but the graph is *generated* from an application-level policy; nodes contain no logic |
| Style | OOP, clean code, rich domain model, hexagonal (ports & adapters) |

The HTTP/SSE contract (`POST /v1/stream`, request fields, SSE event types) does **not** change:
homelab-ui keeps working as is.

---

## 1. Why redesign

What the code review found (2026-10-01, ~4,700 lines read):

1. **The agent's rules live in adapters, twice.** Intent, plan, verdict, outcome, limits and
   the routing rules exist once per engine (7 files identical or near-identical, 4 prompt
   modules near-identical) and have already drifted apart (reflection skip rule, history
   windows, memory model). Every feature had to be written twice.
2. **The workflow is implicit.** "Understand → plan / clarify / act → tools → check → answer"
   is spread over a router, 10 nodes, graph edges and a mutable bag of flags (`TurnState`:
   `plan`, `reflection`, `retries`, `iteration`, `answer`, `outcome`, …) that any node may
   change. No single place answers "what happens next, and why?".
3. **The hexagon is inverted in places.** Ports are declared inside adapters
   (`adapter/outbound/tool/tool_port.py`, `langgraph/port`, `anthropic_sdk/port`); the only use
   case forwards a black-box stream; the DI holds logic (`MODEL_ALIASES`, role resolution).
4. **Presentation leaks into the core.** Nodes emit UI sentences ("Understanding your
   request", "Running echo") through `get_stream_writer`; branding sits in the act prompt.
5. **"How" choices force "what" changes.** With no domain concept for "the answer needs
   tools", every attempt to signal it touched router, nodes, prompts and both engines.

Goal: **one copy of every rule, each rule in one obvious place, every dependency pointing
inwards**, so a feature is a small change in one layer.

---

## 2. The target in one picture

```
                    ┌──────────────────────── inbound adapters ────────────────────────┐
  homelab-ui ──SSE──│ web: StreamController ── SsePresenter (TurnEvent → SSE wording)  │
                    └──────────────────────────────┬───────────────────────────────────┘
                                                   │ HandleMessagePort
┌──────────────────────────────── application ─────▼───────────────────────────────────┐
│ HandleMessage (use case)                                                              │
│   loads Conversation ─► starts Turn ─► WorkflowRunner.run(turn) ─► closes ─► saves    │
│                                                                                       │
│ Steps (one class each): Understand · Plan · Clarify · Act · RunTools · Review ·       │
│                         Feedback · Finish · Summarize                                 │
│                                                                                       │
│ Outbound ports: IntentClassifier · Planner · Actor · Reviewer · Summarizer ·          │
│   ToolCatalog · ToolExecutor · ConversationRepository · TurnEventPublisher ·          │
│   ModelRegistry · WorkflowRunner                                                      │
└───────────────────────────────────────┬──────────────────────────────────────────────┘
                                        │ depends on
┌───────────────────────────────── domain (pure Python) ───────────────────────────────┐
│ Conversation (aggregate) · Turn · Understanding · Intent · Plan · Draft · ToolCall ·  │
│ ToolResult · Verdict · Answer · Outcome · Limits · TurnPolicy · Step · TurnEvent      │
└───────────────────────────────────────────────────────────────────────────────────────┘
                                        ▲ implemented by
┌──────────────────────────────── outbound adapters ───────────────────────────────────┐
│ langgraph: LangGraphWorkflowRunner (graph generated from Step + TurnPolicy)           │
│ llm/langchain: LangChainIntentClassifier · Planner · Actor · Reviewer · Summarizer    │
│                + one prompts/ package                                                 │
│ tool/mcp: McpToolCatalog · McpToolExecutor                                            │
│ persistence/mongo: MongoConversationRepository                                        │
│ events: QueueTurnEventPublisher                                                       │
└───────────────────────────────────────────────────────────────────────────────────────┘
bootstrap: config → ModelRegistry, settings; DI = wiring only
```

Dependency rule: `domain` imports nothing from the project; `application` imports `domain`
only; adapters import `application` ports and `domain`; `bootstrap` imports everything.
`tests/architecture` enforces it.

---

## 3. Domain model

Plain dataclasses and enums with behaviour. No pydantic, no LangChain, no I/O.

### 3.1 Conversation (aggregate root)

The only entry point to change a conversation. Owns the history, the summary and the plan
waiting for approval.

```python
class Conversation:
    id: ConversationId
    messages: list[Message]            # user / assistant, final answers only
    summary: Summary | None
    pending_plan: Plan | None

    def start_turn(self, text: str) -> Turn: ...
    def recent(self, limit: int) -> list[Message]: ...
    def propose(self, plan: Plan) -> None: ...              # sets pending_plan
    def take_pending_plan(self) -> Plan | None: ...         # approval consumes it
    def close(self, turn: Turn) -> None: ...                # appends user + answer,
                                                            # keeps or drops the pending plan
    def needs_summary(self, budget: TokenBudget) -> bool: ...
    def compact(self, summary: Summary, keep_last: int) -> None: ...
```

Invariant kept in one place: **a pending plan survives a turn only if the turn's intent keeps
it** (`intent.keeps_pending_plan`).

### 3.2 Turn (entity)

One user message and everything the agent does for it. Mutated only through intention-revealing
methods; each one records what happened, so the policy can read the turn instead of flags.

```python
class Turn:
    request: str
    understanding: Understanding | None
    plan: Plan | None                  # approved plan being executed
    drafts: list[Draft]                # act outputs, in order
    evidence: list[ToolResult]
    verdicts: list[Verdict]
    answer: Answer | None              # set once, by finish()

    def understood(self, understanding: Understanding) -> None: ...
    def execute(self, plan: Plan) -> None: ...
    def drafted(self, draft: Draft) -> None: ...
    def observed(self, results: list[ToolResult]) -> None: ...
    def reviewed(self, verdict: Verdict) -> None: ...
    def finish(self, answer: Answer) -> None: ...

    @property
    def last_draft(self) -> Draft | None: ...
    @property
    def steps_taken(self) -> int: ...          # replaces `iteration`
    @property
    def retries(self) -> int: ...              # derived from verdicts, no counter to keep in sync
    @property
    def used_tools(self) -> bool: ...
```

### 3.3 Value objects

| Object | Holds | Behaviour |
|---|---|---|
| `Intent` (enum) | task, continuation, direct, plan_approval, plan_revision, ambiguous | `needs_plan`, `keeps_pending_plan` |
| `Understanding` | intent, standalone query, success criteria, clarification question | `normalized(pending_plan)`: approval without a plan → direct; ambiguous without a question → task |
| `Plan` | task, steps | — |
| `Draft` | text, tool calls | `asks_for_tools` (has tool calls) |
| `ToolCall` / `ToolResult` | id, name, arguments / output or error | `ToolResult.failed` |
| `Verdict` | accept or retry, critique | `rejects` |
| `Answer` | text, `Outcome` | factory methods: `answered`, `best_effort`, `budget_exhausted`, `awaiting_approval`, `clarification`, `none` |
| `Limits` | max steps, max retries | `allows_another_step(turn)`, `allows_retry(turn)` |
| `TurnEvent` | understanding, planning, running tools (names), checking, retrying, token, reset, finished | what happened, never UI wording |

### 3.4 Step and TurnPolicy — the workflow, in one class

```python
class Step(StrEnum):
    UNDERSTAND = "understand"; PLAN = "plan"; CLARIFY = "clarify"; ACT = "act"
    RUN_TOOLS = "run_tools"; REVIEW = "review"; FEEDBACK = "feedback"; FINISH = "finish"

class TurnPolicy:
    def __init__(self, limits: Limits) -> None: ...
    def next(self, done: Step, turn: Turn) -> Step: ...     # the only routing function
```

`next` encodes today's behaviour exactly (nothing new added during the refactor):

| After | Condition | Next |
|---|---|---|
| understand | intent needs a plan (task, plan_revision) | plan |
| understand | ambiguous | clarify |
| understand | plan_approval (pending plan taken) | act |
| understand | anything else (direct, continuation) | act |
| plan | — (plan proposed, waits for the user) | finish |
| clarify | — | finish |
| act | draft has tool calls and `limits.allows_another_step` | run_tools |
| act | draft has tool calls, step budget spent | finish (budget exhausted) |
| act | no tool calls, intent direct, no tool used | finish (no review) |
| act | no tool calls otherwise | review |
| run_tools | — | act |
| review | verdict rejects and `limits.allows_retry` and steps left | feedback |
| review | otherwise | finish |
| feedback | — | act |

`Finish` turns the turn into an `Answer` with the same rules as today (`FinalizeNode._settle`):
no draft → `none`; draft still has tool calls → `budget_exhausted`; last verdict rejects →
`best_effort` with the draft; otherwise `answered`.

Every later feature becomes a row in this table or a factory on `Answer`, tested in isolation
(see §10).

---

## 4. Application layer

### 4.1 Ports (all in `application/port/`, as `Protocol`s)

Inbound:

| Port | Method |
|---|---|
| `HandleMessagePort` | `handle(request: AgentRequest) -> None` (events go to the publisher) |

Outbound, named by **role**, not technology:

| Port | Method | Used by step |
|---|---|---|
| `IntentClassifier` | `understand(conversation, turn) -> Understanding` | Understand |
| `Planner` | `plan(conversation, turn, tools) -> Plan` | Plan |
| `Actor` | `act(conversation, turn, tools) -> Draft` | Act |
| `Reviewer` | `review(conversation, turn) -> Verdict` | Review |
| `Summarizer` | `summarize(conversation) -> Summary` | Summarize |
| `ToolCatalog` | `tools() -> list[ToolSpec]` | Plan, Act |
| `ToolExecutor` | `run(call: ToolCall) -> ToolResult` | RunTools |
| `ConversationRepository` | `load(id) -> Conversation`, `save(conversation)` | HandleMessage |
| `TurnEventPublisher` | `publish(event: TurnEvent)` | every step |
| `ModelRegistry` | `for_role(role, selected) -> ModelProfile` | LLM adapters (via bootstrap) |
| `WorkflowRunner` | `run(conversation, turn) -> None` | HandleMessage |

`Actor` returns a `Draft`. **How** an adapter obtains it (tool calling, structured output, a
marker) is the adapter's business; the policy only ever sees `Draft`.

### 4.2 Steps (one class per step)

```python
class StepHandler(Protocol):
    step: Step
    async def run(self, conversation: Conversation, turn: Turn) -> None: ...
```

Each handler is a few lines: call one port, record the result on the turn, publish one event.

```python
class ActStep:
    step = Step.ACT
    async def run(self, conversation, turn):
        draft = await self._actor.act(conversation, turn, await self._catalog.tools())
        turn.drafted(draft)

class RunToolsStep:
    step = Step.RUN_TOOLS
    async def run(self, conversation, turn):
        calls = turn.last_draft.tool_calls
        await self._events.publish(TurnEvent.running_tools([c.name for c in calls]))
        turn.observed(await gather(*(self._executor.run(c) for c in calls)))
```

### 4.3 The use case

```python
class HandleMessage:
    async def handle(self, request: AgentRequest) -> None:
        conversation = await self._conversations.load(request.conversation_id)
        turn = conversation.start_turn(request.message)
        await self._workflow.run(conversation, turn)          # steps + policy, see §5
        conversation.close(turn)
        if conversation.needs_summary(self._budget):
            conversation.compact(await self._summarizer.summarize(conversation), keep_last=4)
        await self._conversations.save(conversation)
        await self._events.publish(TurnEvent.finished(turn.answer))
```

Error handling (today in `StreamAgentUseCase`): an `AgentUnavailable` from any port becomes the
"temporarily unavailable" error event; anything else becomes an error event with the trace.
Same behaviour, one place.

---

## 5. LangGraph adapter — the runtime, generated from the policy

`LangGraphWorkflowRunner` implements `WorkflowRunner`. It owns no rule: it turns the list of
step handlers and the policy into a graph.

```python
class LangGraphWorkflowRunner:
    def __init__(self, handlers: list[StepHandler], policy: TurnPolicy) -> None:
        graph = StateGraph(TurnGraphState)
        for handler in handlers:
            graph.add_node(handler.step, _node(handler))
            graph.add_conditional_edges(
                handler.step,
                lambda state, done=handler.step: _to_end(policy.next(done, state["turn"])),
            )
        graph.set_entry_point(Step.UNDERSTAND)
        self._graph = graph.compile()

    async def run(self, conversation, turn) -> None:
        await self._graph.ainvoke({"conversation": conversation, "turn": turn})
```

- **State** is `{"conversation": Conversation, "turn": Turn}`: live domain objects, no
  pack/unpack per node. This works because the graph runs **without a checkpointer**: the
  conversation is persisted by `ConversationRepository` at the end of the turn.
- **Adding a step** = a `Step` value, a handler class, and its rows in `TurnPolicy`. The graph
  follows automatically; there is no edge list to keep in sync.
- **Streaming**: steps publish `TurnEvent`s through `TurnEventPublisher`; LangGraph's stream
  writer is no longer used.
- **What LangGraph still gives**: a runtime with a visual graph (`get_graph().draw_mermaid()`,
  LangGraph Studio), recursion limits, and an easy path to checkpointing or `interrupt()` later
  (would then need a serializable state mapper in this adapter only).

---

## 6. LLM adapters (`adapter/outbound/llm/langchain/`)

One class per role port, all built on LangChain `ChatOpenAI` against the homelab llama-swap
server:

| Class | Port | Call style |
|---|---|---|
| `LangChainIntentClassifier` | `IntentClassifier` | structured output → DTO → `Understanding` |
| `LangChainPlanner` | `Planner` | text → `Plan` |
| `LangChainActor` | `Actor` | tools bound only under an approved plan → `Draft` |
| `LangChainReviewer` | `Reviewer` | structured output → `Verdict` |
| `LangChainSummarizer` | `Summarizer` | text → `Summary` |

- **One `prompts/` package** (context, plan, act, review, summary, tool catalog, clock). The
  duplicated per-engine prompt modules disappear. Branding ("You are BlueAI…") becomes a
  configured assistant name.
- **Pydantic DTOs** for structured output live here and map to domain objects; the domain does
  not depend on pydantic.
- **`ContextWindow`** (history trimming, token counting) is an adapter service used by these
  classes.
- **Model per role**: each adapter receives a `ModelProfile` resolved by `ModelRegistry` for its
  role (act, context, plan, reflection, summary), with the existing rule: `model: null` = the
  model selected in the UI. Thinking (`chat_template_kwargs.enable_thinking`), streaming and
  token limits come from the profile, in one `ChatModelFactory`.
- Model errors that are retryable map to `AgentUnavailable` here (today in `LangGraphAgent`).

---

## 7. Other adapters

| Adapter | Implements | Notes |
|---|---|---|
| `tool/mcp/McpToolCatalog`, `McpToolExecutor` | `ToolCatalog`, `ToolExecutor` | today's MCP code, already clean; tools discovered at boot from `toolbox` + `external_mcp_*` |
| `persistence/mongo/MongoConversationRepository` | `ConversationRepository` | one collection `conversations`, document = `Conversation` (messages, summary, pending plan), TTL index; mapper document ↔ domain |
| `events/QueueTurnEventPublisher` | `TurnEventPublisher` | an asyncio queue per request (today `SSEQueue`) |
| `inbound/web/StreamController` + `SsePresenter` | `HandleMessagePort` caller | the presenter is the **only** place with UI wording: `TurnEvent.running_tools(["echo"])` → `status: "Running echo"` |

---

## 8. Bootstrap

- `ModelRegistry` is built from `config/<env>/operation/llm.yml` and `agent.yml`: aliases
  (`qwen3.5-0.8b` → key `qwen3_5-0_8b`) and roles come from YAML, `MODEL_ALIASES` leaves the
  code.
- DI only wires: settings → config → adapters → steps → policy → runner → use case →
  controller. No branching on engines, no business decisions.
- `AGENT_ENGINE`, `LITELLM_*`, `ANTHROPIC_*`, `AGENT_SDK_TOOLS` settings are removed.

---

## 9. Target folder tree

```
src/agent_orchestrator/
  domain/
    conversation/   conversation.py  message.py  summary.py
    turn/           turn.py  understanding.py  intent.py  plan.py  draft.py  verdict.py
                    answer.py  outcome.py
    tool/           tool_spec.py  tool_call.py  tool_result.py
    policy/         step.py  turn_policy.py  limits.py
    event/          turn_event.py
    model/          model_profile.py  role.py
    exception/      agent_unavailable.py  unknown_tool.py
  application/
    port/inbound/   handle_message_port.py
    port/outbound/  intent_classifier.py  planner.py  actor.py  reviewer.py  summarizer.py
                    tool_catalog.py  tool_executor.py  conversation_repository.py
                    turn_event_publisher.py  model_registry.py  workflow_runner.py
    step/           understand.py  plan.py  clarify.py  act.py  run_tools.py  review.py
                    feedback.py  finish.py
    handle_message.py
  adapter/
    inbound/web/    stream_controller.py  sse_presenter.py  schema/
    outbound/
      langgraph/    langgraph_workflow_runner.py
      llm/langchain/  chat_model_factory.py  intent_classifier.py  planner.py  actor.py
                      reviewer.py  summarizer.py  context_window.py  dto/  prompts/
      tool/mcp/     mcp_tool_catalog.py  mcp_tool_executor.py  session_factory.py
      persistence/mongo/  mongo_conversation_repository.py  conversation_document.py
      events/       queue_turn_event_publisher.py
src/bootstrap/      settings, configuration, model_registry_factory.py, di/, router/, application/
```

Size estimate: the two engines (~2,800 lines) become ~1,200 lines of domain + application +
adapters, each file small and single-purpose.

---

## 10. Testing strategy

| Layer | Tests | Fakes |
|---|---|---|
| domain | `TurnPolicy` table-driven (one case per row of §3.4), `Conversation` invariants, `Finish` rules | none |
| application | each step with fake ports; `HandleMessage` end to end with an in-memory runner | fake classifier/planner/actor/reviewer, in-memory repository, list publisher |
| adapters | LangChain adapters with a fake chat model (prompt in, DTO out), Mongo repository against a test DB, MCP adapter (existing tests), SSE presenter mapping | — |
| runtime | `LangGraphWorkflowRunner` runs the same scenarios as the in-memory runner and must give identical turns | fake ports |
| architecture | import rules of §2 | — |

The scenario set (direct, task → approve → execute, clarify, retry, budget exhausted, summary)
is written once and run against both runners.

---

## 11. Migration plan

Each step ends green (`make check`) and keeps the HTTP contract.

| # | Step | Done when |
|---|---|---|
| 0 | **Pin behaviour**: scenario tests through `/v1/stream` with fake LLMs (LangGraph engine) | the scenario set of §10 passes on today's code |
| 1 | **Drop the Claude SDK engine**: delete `adapter/outbound/anthropic_sdk`, `llm/lite_llm`, `bootstrap/di/anthropic_sdk_di.py`, its settings, tests, `claude-agent-sdk`/`anthropic` deps, `run_sdk` target, SDK docs | only LangGraph remains, scenario tests pass |
| 2 | **Domain**: create §3 objects + `TurnPolicy` with unit tests (not wired yet) | domain tests pass, architecture test added |
| 3 | **Application**: ports, step handlers, `HandleMessage`, in-memory runner; tests with fakes | application tests pass |
| 4 | **Adapters**: LangChain role adapters + one prompts package, MCP catalog/executor behind the new ports, Mongo repository, queue publisher, SSE presenter | adapter tests pass |
| 5 | **LangGraph runner** generated from the policy; wire everything in bootstrap; switch the controller to `HandleMessage` | scenario tests from step 0 pass on the new stack |
| 6 | **Delete the old engine** (`adapter/outbound/langgraph/*` old nodes, router, state, serialization), `MODEL_ALIASES`, checkpointer config | no dead code, docs updated (`Readme.md`, `readme_interne.md`; SDK guides removed) |

After step 6, the features dropped by the reset come back as small changes, each in one place:

| Feature | Where it goes |
|---|---|
| auto-approve (request option) | `AgentRequest.options` → `Turn` → one row in `TurnPolicy` (after plan: act instead of finish) |
| "needs tools" escalation | `Verdict` gains `needs_tools` → one row in `TurnPolicy` (after review, no plan: plan) |
| act asks for a plan | `Draft.needs_plan(reason)` produced by `LangChainActor` however it detects it → one row in `TurnPolicy` |
| never show a rejected draft | `Answer.unverified(critique)` used by `Finish` instead of `best_effort` with the draft |
| per-request thinking, model freeze | `ModelRegistry` / `ChatModelFactory` only |

---

## 12. Open points to confirm

1. **Checkpointing**: the plan runs the graph without a checkpointer (the conversation store is
   the source of truth). Fine for now? Resuming a half-finished turn after a crash would then
   not be possible (it is not today in practice either).
2. **Tool discovery**: tools are discovered once at boot today. Keep that, or let
   `McpToolCatalog` refresh on a timer?
3. **Summary trigger**: keep "more than 4 messages and over half of the act model's context",
   or move the numbers to config?
