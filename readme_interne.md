# agent-orchestrator — internal guide

How the service works inside: layers, the turn workflow, every step, what it records and what
the user sees. Written for the architecture introduced on 2026-10-01 (see
`design_clean_architecture.md`). The guides of the previous engines are in `sandbox/archive/`.

---

## 1. What the service is

One HTTP endpoint, `POST /v1/stream`, that answers a chat message as a stream of SSE events.
For each message the agent:

1. **understands** it against the conversation (intent, standalone request, success criteria);
2. either **answers** directly, **asks** a clarifying question, or **proposes a plan** for a
   task that needs tools, and waits for the user's approval (or carries it out at once when
   the request sets `auto_approve`);
3. once a plan is approved, **acts**: calls tools (MCP), reads their results, writes the answer;
4. **reviews** the answer (when there is something to check) and rewrites it if rejected;
5. **keeps** the exchange in the conversation, summarising old history when it grows.

Models are served by the homelab (OpenAI-compatible llama-swap); tools by agent-toolbox (MCP);
conversations are stored by the LangGraph MongoDB checkpointer (SQLite fallback).

---

## 2. Layers and folder map

```
src/agent_orchestrator/
  domain/        pure Python: the agent's concepts and rules (no framework, no pydantic)
    conversation/   Conversation (aggregate), Message, Speaker
    turn/           Turn, Understanding, Intent, Plan, Draft, Feedback, Verdict, Answer,
                    Outcome, TurnSettings
    tool/           ToolSpecification, ToolCall, ToolResult
    workflow/       Step, TurnPolicy (every routing rule)
    event/          TurnEvent (what happened, never UI wording)
    exception/      AgentUnavailable, UnknownModel, UnknownTool, ToolUnavailable
  application/   the use case and the steps; depends on the domain only
    port/inbound/   HandleMessagePort, AgentRequest
    port/outbound/  IntentClassifier, Planner, Actor, Reviewer, Summarizer, TokenCounter,
                    ToolCatalog, ToolExecutor, ModelRegistry, TurnEventStream, WorkflowRunner
    step/           one class per step (+ StepHandler protocol)
    use_case/       HandleMessage
  adapter/
    inbound/web/    StreamAgentController, SsePresenter (the only UI wording), schemas
    outbound/
      langgraph/    node/   AgentNode base + one node class per step (delegates to the step
                            handler; overridden only to use a LangGraph feature), agent_nodes
                    graph/  AgentGraphBuilder (edges from TurnPolicy.targets), PolicyRouter
                    state/  GraphState, TurnStateCodec (domain ↔ JSON checkpoint)
                    LangGraphWorkflowRunner (runs the compiled graph, loads the conversation)
      llm/          ModelCatalog (+ AgentRole), ModelSettingsMapper, thinking switch
      llm/langchain/  one adapter per role port, ChatModels, ContextWindow, messages,
                      model_call, token_counter, prompts/ (one package)
      tool/         Toolbox (ToolCatalog + ToolExecutor), ToolRegistry, mcp/
      event/        QueueTurnEventStream
src/bootstrap/   settings, configuration, AgentDI (wiring only), container, routers
```

Dependency rule, enforced by `tests/architecture/test_boundaries.py`: the domain imports
nothing from the project or any framework; the application imports the domain only; adapters
implement application ports; only `bootstrap` imports everything.

---

## 3. One request, end to end

```
homelab-ui ──POST /v1/stream {message, model_name, request_id, auto_approve}
                                                                ▼
StreamAgentController ── admission (MAX_CONCURRENT_STREAMS, else 503)
   │  sets request_id_context (every log line carries it)
   │  creates a QueueTurnEventStream, starts HandleMessage.handle(request, events) as a task
   │  reads the stream: each TurnEvent ─► SsePresenter ─► SSE bytes; then `complete`
   ▼
HandleMessage
   │  Turn(request, model, settings = ModelRegistry.turn_settings(model))
   │  for event in WorkflowRunner.run(conversation_id = request_id, turn): publish(event)
   │  AgentUnavailable ─► failed("temporarily unavailable…"); other error ─► failed(trace)
   │  logs "turn finished: <outcome>, <steps>/<max> steps in <s>" or "turn cancelled after <s>"
   ▼
LangGraphWorkflowRunner
   │  loads the Conversation of the thread from the checkpointer (new one if none/unreadable)
   │  runs the graph; each AgentNode: decode state ─► publish TurnEvent.entering(step)
   │                                  ─► work = handler.run(conversation, turn) ─► encode state
   │  each conditional edge (PolicyRouter): TurnPolicy.next(step just done, turn)
   │  a streamed reply publishes TurnEvent.answer_delta(text) while the act model writes
   │  at the end: TurnEvent.finished(turn)
```

Events written during a run go through one port, `TurnEventPublisher`. Its LangGraph
implementation, `LangGraphEventPublisher`, writes to the run's custom stream, which the runner
yields. Outside a graph run it publishes nothing.

---

## 4. The domain

**Conversation** — the aggregate root; the only way to change a conversation.

| Method | What it does |
|---|---|
| `interpret(turn, understanding)` | normalises the understanding; an approval takes the pending plan into the turn (and the turn's query becomes the plan's task); any intent that does not keep the pending plan drops it |
| `submit(turn, plan)` | with `turn.options.auto_approve`, the turn executes the plan now; otherwise the plan is proposed and the answer is the approval request |
| `propose(plan)` | stores the plan awaiting approval |
| `close(turn)` | appends the user's message and the answer to `messages` |
| `older_than(n)` / `compact(summary, n)` | what to summarise / keep only the last `n` messages and the summary |

**Turn** — one message and everything done for it. It changes only through intention-revealing
methods (`understood`, `execute`, `drafted`, `observed`, `reviewed`, `give_feedback`, `finish`)
and answers questions derived from what happened: `steps_taken` (= drafts), `retries`
(= feedbacks), `evidence` (= tool results), `used_tools`, `last_draft`, `last_verdict`,
`is_plain_direct_answer`. Its `work` log keeps the order the actor needs to see:
`Draft` (text + tool calls) → `ToolResult` → … → `Feedback` (critique) → `Draft`. A draft can
also ask for a plan (`Draft.asking_for_plan(reason)`) when the answer needs tools the turn
cannot use. `execute(plan)` starts the work log afresh: what was drafted before the plan was
approved (e.g. that plan request) is not part of carrying it out.

`Turn.conclude()` turns the work into an answer when no step settled it earlier:

| Last draft | Answer | Outcome |
|---|---|---|
| none | "No answer was produced." | `best_effort` |
| still asks for tools (budget spent) | "I reached the step limit…" | `budget_exhausted` |
| last verdict rejects it | the draft | `best_effort` |
| otherwise | the draft | `answered` |

Other value objects: `Intent` (`needs_plan`, `keeps_pending_plan`), `Understanding`
(`fallback` = task, `normalized`: approval without plan → direct, ambiguous without question →
task), `Plan`, `Verdict` (`rejects`), `Answer` (factories: `answered`, `best_effort`, `nothing`,
`budget_exhausted`, `approval_request(plan)`, `clarification(question)`), `TurnSettings`
(`max_steps`, `max_retries`, `context_tokens`, from the act model), and
`TurnOptions` (`auto_approve`: the user's choices for this message, set from the request).

---

## 5. The workflow — `TurnPolicy`

Every routing rule lives in `domain/workflow/turn_policy.py`, as an ordered table of
`Transition(source, target, when)`; `when` is a named predicate from `conditions.py`. After a
step, the first transition whose condition holds is taken (`TurnPolicy.next`). The same table
gives the graph its edges (`TurnPolicy.targets`), so the graph cannot drift from the rules:
`AgentGraphBuilder` adds a plain edge when a step has one target, a conditional edge (asking
the policy) when it has several. `test_agent_graph.py` checks the compiled edges equal the
transitions.

```python
TRANSITIONS = (
    Transition(UNDERSTAND, PLAN, needs_plan),
    Transition(UNDERSTAND, CLARIFY, is_ambiguous),
    Transition(UNDERSTAND, ACT),
    Transition(PLAN, ACT, has_approved_plan),
    Transition(PLAN, FINISH),
    Transition(CLARIFY, FINISH),
    Transition(ACT, PLAN, asks_for_plan_without_one),
    Transition(ACT, FINISH, asks_for_tools_out_of_steps),
    Transition(ACT, RUN_TOOLS, asks_for_tools),
    Transition(ACT, FINISH, is_plain_direct_answer),
    Transition(ACT, REVIEW),
    Transition(RUN_TOOLS, ACT),
    Transition(REVIEW, FEEDBACK, retry_allowed),
    Transition(REVIEW, FINISH),
    Transition(FEEDBACK, ACT),
    Transition(FINISH, SUMMARIZE),
    Transition(SUMMARIZE, END),
)
```

The generated graph (`graph.get_graph().draw_mermaid()`; dotted = decided by the policy):

```
__start__ --> understand
understand -.-> plan | clarify | act
plan -.-> act | finish      clarify --> finish
act -.-> plan | finish | run_tools | review
run_tools --> act          feedback --> act
review -.-> feedback | finish
finish --> summarize --> __end__
```

```
          ┌──────────── UNDERSTAND ────────────┐
   task / revision      ambiguous       direct / continuation / approval
          ▼                 ▼                   ▼
        PLAN            CLARIFY               ACT ◄────────────┬──────────┐
          │                 │          tools asked & steps left │          │
          │                 │                   ├──► RUN_TOOLS ─┘          │
          │                 │   plain direct    │                          │
          │                 │   or budget spent │ otherwise                │
          ▼                 ▼                   ▼                          │
        FINISH ◄────────────┴────────────── REVIEW ── rejected & limits ─► FEEDBACK
          │
       SUMMARIZE ─► END
```

| After | Condition | Next |
|---|---|---|
| understand | intent needs a plan (task, plan_revision), or none | plan |
| understand | ambiguous | clarify |
| understand | direct, continuation, plan_approval | act |
| plan | the turn holds the plan (auto-approved) | act |
| plan, clarify | otherwise / — | finish (the plan waits for the user's yes) |
| act | draft asks for a plan and the turn has none | plan (the route had no tools) |
| act | draft asks for tools, steps left | run_tools |
| act | draft asks for tools, `steps_taken >= max_steps` | finish (budget exhausted) |
| act | plain direct answer (direct intent, no tool used) | finish (no review) |
| act | otherwise | review |
| run_tools, feedback | — | act |
| review | verdict rejects and `retries < max_retries` and `steps_taken < max_steps` | feedback |
| review | otherwise | finish |
| finish | — | summarize |
| summarize | — | end |

---

## 6. Steps

| Step | Port | Records | Status shown |
|---|---|---|---|
| `UnderstandStep` | `IntentClassifier` (None → `Understanding.fallback`) | `conversation.interpret(turn, …)` | "Understanding your request" |
| `PlanStep` | `Planner`, `ToolCatalog` | `conversation.submit(turn, plan)` | "Preparing a plan" |
| `ClarifyStep` | — (question written while understanding) | answer = clarification | — |
| `ActStep` | `Actor`, `ToolCatalog` | `turn.drafted(draft)` | — |
| `RunToolsStep` | `ToolExecutor` (calls run concurrently) | `turn.observed(results)` | "Running <tools>" |
| `ReviewStep` | `Reviewer` (None → accept + warning) | `turn.reviewed(verdict)` | "Checking the answer" |
| `FeedbackStep` | — | `turn.give_feedback(critique)` | — |
| `FinishStep` | — | answer = `conclude()` if unset, `conversation.close(turn)` | — |
| `SummarizeStep` | `Summarizer`, `TokenCounter` | `conversation.compact(…)` when > 4 messages and > `context_tokens // 2`; a failure only logs | — |

---

## 7. LLM adapters (`adapter/outbound/llm/langchain/`)

| Adapter | Role (`AgentRole`) | Input it builds | Output |
|---|---|---|---|
| `LangChainIntentClassifier` | `agent_context` | rendered history (budget-trimmed), pending plan, latest message | `UnderstandingDto` → `Understanding` |
| `LangChainPlanner` | `agent_plan` | system (task, tools, plan to revise) + history + the request | `Plan(task=query, steps)` |
| `LangChainActor` | `agent_act` | system (request, plan steps or "cannot run tools", catalog) + history + request + the work log | `Draft` (tool ids generated) |
| `LangChainReviewer` | `agent_reflection` | previous exchange + latest message, request, criteria, plan, evidence (clipped 2,000), answer | `VerdictDto` → `Verdict` |
| `LangChainSummarizer` | `agent_summary` | existing summary + older messages | text |

- **Tools are bound only under an approved plan** (`turn.plan`), and only if there are tools.
- **Outside a plan the actor can ask for one**: it binds a single tool, `request_plan(reason)`
  (`plan_request.py`), never the real tools. `direct_draft` turns a `request_plan` call into
  `Draft.asking_for_plan(reason)`, and any other tool call into `asking_for_plan("run <names>")`.
  A tool call rather than a text line, so a streamed reply never has to be read before it is
  shown. Watch for over-calling: when the real tools were bound here, the models tested called
  them even for questions about the tools.
- **How a reply is read** (`reply/`): a `ReplyReader` reads the model's reply. `WholeReply` makes
  one call. `StreamedReply` streams it, publishes each text piece as `TurnEvent.answer_delta`
  and returns the merged reply (tool calls included). The actor uses its `final_reply` reader
  only when `turn.is_plain_direct_answer` (the policy finishes such a turn without review, so the
  streamed text is the answer); every other call uses `WholeReply`. `AgentDI._final_reply`
  picks the reader from `AGENT_ANSWER_DELIVERY` (`stream` → `StreamedReply`, `whole` →
  `WholeReply`).
- **The context prompt is an ordered checklist**: approval, revision, task, continuation,
  direct, ambiguous; the first that applies wins. `task` is limited to the user's own data,
  files, records or systems, or running code. Explaining concepts, how things work,
  comparisons, alternatives or good practices is `direct`, even when technical. A few short
  examples close the prompt: the context model runs without reasoning, and examples steer
  it better than more rules.
- **The review prompt depends on whether a tool ran**: with tool evidence, an answer that
  contradicts it or states data not in it is retried; without evidence, general knowledge
  is allowed and only a wrong answer, or the user's own data the conversation does not
  give, is retried. Without that split, a strict reviewer rejected every technical detail
  of a plain explanation as "not in the evidence".
- **`ContextWindow`** puts the conversation summary in the system message, then as much recent
  history as fits `turn.settings.context_tokens` (estimated tokens), then the tail.
- **`ChatModels`** builds one `ChatOpenAI` per (role, selected model), with the
  thinking switch (`chat_template_kwargs.enable_thinking` from `reasoning_effort`).
- **`model_call.model_errors`** maps a retryable LangChain `ModelError` to
  `AgentUnavailableException`, for `invoke` and for the streamed reply.
- **Prompts**: one package, `prompts/` (act, context, plan, review, summary, tool_catalog, clock).

**Models and roles** (`ModelCatalog`, built in `AgentDI._model_catalog`):

- every API operation of `llm.yml` that is not an agent role is a selectable model, keyed by its
  `parameters.model` (the server's name, which is what the UI sends);
- a role of `agent.yml` with `model: <name>` is frozen to it with its own parameters; with
  `model: null` it follows the selected model and its `llm.yml` parameters;
- `turn_settings(model)` reads the act role's parameters: `max_iterations` → `max_steps`,
  `max_reflection_retries` → `max_retries`, `max_context_tokens`;
- an unknown model raises `UnknownModelException` (the request ends with an error event).

---

## 8. Conversation storage

The LangGraph checkpointer (MongoDB, or SQLite when MongoDB is unreachable) stores, per thread
(`thread_id = request_id` = the UI's conversation id), the graph state:

```json
{"conversation": {"id": …, "messages": [{"speaker": "user", "text": …}, …],
                  "summary": …, "pending_plan": {"task": …, "steps": …} | null},
 "turn": {…the last turn, including its work log…}}
```

`TurnStateCodec` converts with pydantic `TypeAdapter`s over the domain dataclasses (the `kind`
field of `Draft` / `ToolResult` / `Feedback` keeps the work log's union unambiguous). A thread
whose state is missing or in an older layout starts a new conversation (warning logged): nothing
is migrated from the previous engines.

---

## 9. Events and SSE

| `TurnEvent` | SSE |
|---|---|
| `step_started(understand / plan / review)` | `status`: "Understanding your request" / "Preparing a plan" / "Checking the answer" |
| `step_started(run_tools)` | `status`: "Running echo, file_reader" |
| `step_started(other steps)` | nothing |
| `answer_delta` | `token` {content: the piece} |
| `finished` | `final` {session_id, content, metadata {iteration, max_iteration, outcome}} |
| `failed` | `error` {content} |
| end of stream | `complete` |

A streaming failure in the controller itself sends a `final` frame with `error` (trace).

---

## 10. Errors

| Where | What happens |
|---|---|
| model unreachable / 5xx (retryable `ModelError`) | `AgentUnavailableException` → `error` "temporarily unavailable…" |
| unknown model | `UnknownModelException` → `error` with the trace |
| unreadable classification | treated as a task (safe: leads to a plan) |
| unreadable review | draft accepted |
| tool unknown or raising | failed `ToolResult` ("Error: …") handed to the model |
| MCP server down at boot | skipped, tools from the others only |
| summary fails | history kept, warning |
| client disconnects | use-case task cancelled, admission released |

---

## 11. Tests

| Folder | What |
|---|---|
| `tests/agent_orchestrator/domain/` | `TurnPolicy` table (one case per rule), `Conversation`, `Turn`, `Understanding` |
| `tests/agent_orchestrator/application/` | each step and `HandleMessage` with fake ports (`fakes.py`, incl. `InMemoryWorkflowRunner`) |
| `tests/agent_orchestrator/scenarios/` | whole turns on **both** runners (plain loop and LangGraph with a checkpointer): same answers, events and stored conversation |
| `tests/agent_orchestrator/adapter/` | LangChain role adapters (fake chat model), catalog, window, prompts, toolbox, MCP, presenter, controller |
| `tests/bootstrap/` | settings, DI (catalog from config, graph has one node per step), container |
| `tests/architecture/` | the dependency rule |
| `tests/evaluation/` | DeepEval against real models (`make test_evaluation`, deselected by default) |

---

## 12. How to…

- **Add a routing rule**: a `Transition` in `TurnPolicy.TRANSITIONS` (with a named condition in
  `conditions.py` if it needs one) + a test. The graph's edges follow.
- **Add a step**: a `Step` value, a handler class in `application/step/`, a node class in
  `langgraph/node/` (two lines) listed in `NODE_TYPES`, its transitions, and the handler in
  `AgentDI._steps`.
- **Use a LangGraph feature in a step** (interrupt, `Send`, retry policy, a subgraph): override
  `work` in that step's node class; the application step and the policy do not change. Nodes may
  not reach models or tools themselves (`test_langgraph_nodes_only_delegate_to_the_application`).
- **Change how a model is asked something**: the role adapter and its prompt in
  `llm/langchain/`; the domain does not change.
- **Add a model**: `llm.yml` entry + `root.yml` line + the UI list (key without dots,
  `parameters.model` = the server's name).
- **Freeze a role to a model**: `model: <name>` in its `agent.yml` entry.
- **Add an MCP server**: a connector named `external_mcp_*` in `connector/mcp.yml` + `root.yml`;
  its tools join the catalog at boot.

---

## 13. Changelog

**2026-10-02 — auto-approve plans.** The request takes `auto_approve` (default false; a
checkbox in the UI settings). It becomes `Turn.options` (`TurnOptions`), and
`Conversation.submit` decides: execute the plan in this turn, or propose it and wait. The
policy has one more row, `PLAN → ACT when has_approved_plan`, so the graph gained one edge;
no flag was added to the graph or the steps. `Turn.execute` now clears earlier drafts, so a
direct route that asked for a plan carries it out with a clean work log.

**2026-10-01 — explicit LangGraph nodes; policy as a transition table.** Each step has its own
node class (`langgraph/node/`), which delegates to the application step handler and is the
place for future LangGraph features (subgraphs, interrupts). `TurnPolicy` became an ordered
table of transitions with named conditions; `AgentGraphBuilder` builds the edges from it
(16 edges, matching the rules, instead of every node declared as reaching every other).
Behaviour is unchanged: the policy and scenario tests passed without modification.

**2026-10-01 — act can ask for a plan; context checklist.** A request misread as direct no
longer ends with "I would need a tool": the actor returns a plan request and `TurnPolicy`
routes to `plan` in the same turn. The context prompt checks for a task before a continuation
or a direct answer. Checked on the configured models: "explain change.md" is a task, and even
forced onto the direct route it gets a plan; "what are the available tools?" stays direct.

**2026-10-01 — clean architecture rewrite.** The Claude Agent SDK engine, its LiteLLM gateway
and its stores were removed. The agent's concepts and rules moved into the domain (one copy),
the workflow into application steps driven by `TurnPolicy`, and LangGraph became a runtime that
generates its graph from them. Conversations restart empty (new state layout). The HTTP/SSE
contract did not change.
