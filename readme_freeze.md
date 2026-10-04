# agent-orchestrator: the complete guide

Written on 2026-10-02, against commit `bf563bd` (auto-approve plans). It describes the code as
it is. If it disagrees with the code later, the code wins.

**How to read it.** Sections 1 and 2 give the big picture and the file map. Section 3 introduces
the objects everything else talks about. Section 5 is the walkthrough from the HTTP request to
the answer on screen. Sections 6 and 7 explain how LangGraph fits and every route a message can
take. Sections 8 to 11 cover models, tools, storage and the frontend. Section 13 lists the
surprises worth knowing.

---

## Contents

1. [The big picture](#1-the-big-picture)
2. [Every directory and file](#2-every-directory-and-file)
3. [The objects you need to know](#3-the-objects-you-need-to-know)
4. [Boot: what exists before the first request](#4-boot-what-exists-before-the-first-request)
5. [Walkthrough: from the request to the final answer](#5-walkthrough-from-the-request-to-the-final-answer)
6. [How the plain steps and LangGraph work together](#6-how-the-plain-steps-and-langgraph-work-together)
7. [Routing: every possible path, with scenarios](#7-routing-every-possible-path-with-scenarios)
8. [Models: who is called, with what](#8-models-who-is-called-with-what)
9. [Tools](#9-tools)
10. [What is stored, where, for how long](#10-what-is-stored-where-for-how-long)
11. [How the frontend and the backend communicate](#11-how-the-frontend-and-the-backend-communicate)
12. [Errors, limits and cancellation](#12-errors-limits-and-cancellation)
13. [Things worth knowing](#13-things-worth-knowing)
14. [Tests](#14-tests)
15. [Reasoning cheat sheet](#15-reasoning-cheat-sheet)

---

## 1. The big picture

The service answers one user message at a time. One message is one **turn**. A turn moves
through **steps** (understand, plan, act, run tools, review…). After each step, a **policy**
reads what happened and picks the next step. The conversation (history, summary, plan waiting
for approval) is **stored** between messages.

```
 homelab-ui (Angular)                       agent-orchestrator (FastAPI)
 ────────────────────                       ─────────────────────────────────────────────────
 user types a message
 POST /v1/stream  ───────────────────────►  controller  ─►  HandleMessage use case
   {message, model_name,                                     builds a Turn
    request_id, auto_approve}                                runs the workflow (LangGraph)
                                                               understand ─► plan / clarify / act
                                                               act ⇄ run_tools (MCP toolbox)
                                                               review ⇄ feedback
                                                               finish ─► summarize
                                             events  ◄────── one TurnEvent per step + finished
 SSE frames  ◄─────────────────────────────  SsePresenter turns events into SSE frames
   status / token / final / error / complete
 bubble shows status, then the answer
```

The code is split in four rings (hexagonal architecture). Inner rings never import outer ones;
`tests/architecture/test_boundaries.py` fails the build if they do.

```
┌──────────────────────────────────────────────────────────────────────────┐
│ bootstrap/            composition root: config, DI wiring, FastAPI app   │
│ ┌──────────────────────────────────────────────────────────────────────┐ │
│ │ adapter/            technology: HTTP/SSE, LangChain, LangGraph, MCP  │ │
│ │ ┌──────────────────────────────────────────────────────────────────┐ │ │
│ │ │ application/      use case, step handlers, ports (interfaces)    │ │ │
│ │ │ ┌──────────────────────────────────────────────────────────────┐ │ │ │
│ │ │ │ domain/         Conversation, Turn, Plan, Answer, TurnPolicy │ │ │ │
│ │ │ │                 pure Python dataclasses, no framework        │ │ │ │
│ │ │ └──────────────────────────────────────────────────────────────┘ │ │ │
│ │ └──────────────────────────────────────────────────────────────────┘ │ │
│ └──────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

- **domain** holds the rules: what a turn is, how a plan gets approved, which step follows which.
  It imports nothing but the standard library.
- **application** holds what the service *does*: one use case (`HandleMessage`) and one
  handler per step. It talks to the outside only through **ports**, which are Python
  `Protocol`s (interfaces): `Actor`, `Planner`, `ToolExecutor`, `WorkflowRunner`…
- **adapter** implements the ports with real technology: LangChain for models, MCP for tools,
  LangGraph for running and storing the workflow, FastAPI/SSE for HTTP.
- **bootstrap** reads configuration, creates every object and plugs adapters into ports.

---

## 2. Every directory and file

Paths are relative to the repository root. `__init__.py` files are empty package markers unless
mentioned.

### 2.1 Repository root

| Path | What it is |
|---|---|
| `Makefile` | Commands: `install`, `install_dev`, `test`, `lint`, `fix`, `format`, `typecheck`, `check` (lint + typecheck + tests), `run` (uvicorn on port 8000), `build`, `docker_build`, `evaluation` (model-quality tests) |
| `pyproject.toml` / `uv.lock` | Dependencies (managed by `uv`), ruff and ty settings |
| `Readme.md` | User documentation: install, run, API, configuration |
| `LICENSE` | Licence |
| `devops/docker/Dockerfile` | Container image; runs `uvicorn bootstrap.application.agent_application:app` on port 8000 |
| `config/` | YAML configuration, see 2.2 |
| `src/` | The code, see 2.3 to 2.7 |
| `tests/` | The tests, see section 14 |
| `sandbox/` | Personal notes, not shipped and ignored by git, see 2.8 |

### 2.2 `config/` — configuration

Loaded at boot by pycraftcore's OmegaConf reader. `APP_ENV` picks the folder (`debug` by
default). Values like `${oc.env:LLM_BASE_URL}` come from environment variables, or from `.env`.

| Path | What it holds |
|---|---|
| `config/root.yml` | The index: which connectors and operations exist, by name. A model must be listed here to be loaded |
| `config/debug/connector/api.yml` | `llm_provider`: base URL and auth of the OpenAI-compatible LLM server (llama.cpp, OpenRouter, NVIDIA…) |
| `config/debug/connector/mcp.yml` | `toolbox`: URL of the agent-toolbox MCP server, transport, timeout. Extra servers named `external_mcp_*` are picked up too |
| `config/debug/connector/database.yml` | `mongodb_checkpointer` (preferred) and `sqlite_checkpointer` (fallback) where conversations are stored; `pool.ttl` = expiry in seconds |
| `config/debug/connector/telemetry.yml` | OpenTelemetry collector (traces and logs to Tempo/Loki) |
| `config/debug/operation/llm.yml` | The **selectable models**. Each entry is one model the UI can send in `model_name`; `parameters.model` is the name the UI sends and the name sent to the server |
| `config/debug/operation/agent.yml` | The **agent roles** (`agent_context`, `agent_plan`, `agent_act`, `agent_reflection`, `agent_summary`). A role with `parameters.model` set always uses that model. A role with `model: null` uses the model the user selected. `agent_act` also gives the turn budget: `max_iterations`, `max_reflection_retries`, `max_context_tokens`, `use_streaming` |

### 2.3 `src/` top level

| Path | What it does |
|---|---|
| `src/__init__.py` | Loads `.env`; exposes `APPLICATION_NAME`, `APPLICATION_VERSION` (from package metadata), `APPLICATION_DEPLOYMENT_ENVIRONMENT`, `APPLICATION_AUTHORS_EMAIL` (shown by `/actuator/info`) |
| `src/agent_orchestrator/` | The hexagon: domain, application, adapters |
| `src/bootstrap/` | The composition root |

### 2.4 `src/agent_orchestrator/domain/` — the rules

**`domain/conversation/`**

| File | Contents |
|---|---|
| `conversation.py` | `Conversation`: `id`, `messages`, `summary`, `pending_plan`. The only way to change a conversation. `interpret` (record the understanding; approve or drop the pending plan), `submit` (auto-approve → execute now, else propose and ask), `propose`, `close` (append user message + answer to history), `older_than` / `compact` (summarising) |
| `message.py` | `Speaker` (`user`, `assistant`) and `Message(speaker, text)`: one line of history |

**`domain/turn/`** — one user message and everything done for it

| File | Contents |
|---|---|
| `turn.py` | `Turn`: the central object of a request. Fields `request`, `model`, `settings`, `options`, `understanding`, `plan`, `work`, `verdicts`, `answer`. Methods that change it: `understood`, `execute`, `drafted`, `observed`, `reviewed`, `give_feedback`, `finish`, `conclude`. Questions: `query`, `intent`, `drafts`, `evidence`, `last_draft`, `last_verdict`, `steps_taken`, `retries`, `used_tools`, `is_plain_direct_answer`. `WorkItem = Draft \| ToolResult \| Feedback` |
| `understanding.py` | `Understanding(intent, query, success_criteria, clarification_question)`. `fallback` (unreadable → task), `normalized` (approval with nothing pending → direct; ambiguous without a question → task), `about` (replace the query) |
| `intent.py` | `Intent`: `task`, `continuation`, `direct`, `plan_approval`, `plan_revision`, `ambiguous`. `needs_plan` (task, plan_revision), `keeps_pending_plan` (plan_revision, ambiguous) |
| `plan.py` | `Plan(task, steps)`: `steps` is the Markdown plan the plan model wrote |
| `draft.py` | `Draft(text, tool_calls, plan_request)`: what the act model produced. `asks_for_tools`, `asks_for_plan`, `asking_for_plan(reason)` |
| `feedback.py` | `Feedback(critique)`: the reviewer's critique, handed back to the act model |
| `verdict.py` | `VerdictAction` (`accept`, `retry`) and `Verdict(action, critique)`, `rejects` |
| `answer.py` | `Answer(text, outcome)` with factories `answered`, `best_effort`, `nothing`, `budget_exhausted`, `approval_request(plan)`, `clarification(question)`; the fixed texts (`NO_ANSWER`, `BUDGET_EXHAUSTED`, `APPROVAL_REQUEST`) |
| `outcome.py` | `Outcome`: `answered`, `best_effort`, `budget_exhausted`, `awaiting_approval`, `clarification` (sent to the UI in the final event's metadata) |
| `turn_settings.py` | `TurnSettings(max_steps, max_retries, context_tokens, stream_answer)`: the model's budget, from `agent_act` |
| `turn_options.py` | `TurnOptions(auto_approve)`: the user's choices for this message, from the request |

**`domain/workflow/`** — which step follows which

| File | Contents |
|---|---|
| `step.py` | `Step`: `understand`, `plan`, `clarify`, `act`, `run_tools`, `review`, `feedback`, `finish`, `summarize`, `end` |
| `transition.py` | `Transition(source, target, when)`: one row of the routing table |
| `conditions.py` | The named conditions a transition can test on the turn: `always`, `needs_plan`, `has_approved_plan`, `is_ambiguous`, `asks_for_plan_without_one`, `asks_for_tools`, `asks_for_tools_out_of_steps`, `is_plain_direct_answer`, `retry_allowed` |
| `turn_policy.py` | `TurnPolicy.TRANSITIONS` (the ordered table), `next(done, turn)` (first matching row), `targets(source)` (every possible next step, used to draw graph edges), `FIRST_STEP = understand` |

**`domain/event/`**

| File | Contents |
|---|---|
| `turn_event.py` | `TurnEventKind` (`step_started`, `finished`, `failed`) and `TurnEvent`: `entering(step, turn)`, `finished(turn)`, `failed(error)`. What happened, never how it is shown |

**`domain/tool/`**

| File | Contents |
|---|---|
| `tool_call.py` | `ToolCall(id, name, arguments)`: one call the act model asked for |
| `tool_result.py` | `ToolResult(call_id, tool_name, output, error)`; `content` (output, or `Error: …`); `failure(...)` |
| `tool_specification.py` | `ToolSpecification(name, description, parameters, output_schema)`: a tool as discovered from MCP |

**`domain/exception/`**

| File | Raised when |
|---|---|
| `agent_unavailable_exception.py` | The LLM server fails in a retryable way (down, overloaded) |
| `tool_unavailable_exception.py` | The MCP server cannot be reached after retries, or advertises no tool when tools are required |
| `unknown_model_exception.py` | `model_name` is not a model from `llm.yml` |
| `unknown_tool_exception.py` | The act model calls a tool that does not exist |

### 2.5 `src/agent_orchestrator/application/` — what the service does

**`application/use_case/`**

| File | Contents |
|---|---|
| `handle_message.py` | `HandleMessage.handle(request, events)`: builds the `Turn`, runs the workflow, publishes every event, turns exceptions into a `failed` event, always closes the event stream |

**`application/step/`** — one class per step. Each has `step = Step.X` and
`async run(conversation, turn)`: call at most one port, record the result on the turn or the
conversation.

| File | Port(s) used | What it records |
|---|---|---|
| `step_handler.py` | — | `StepHandler` protocol (`step`, `run`) |
| `understand_step.py` | `IntentClassifier` | `conversation.interpret(turn, understanding)`; unreadable → `Understanding.fallback` |
| `plan_step.py` | `Planner`, `ToolCatalog` | `conversation.submit(turn, plan)` |
| `clarify_step.py` | none | `turn.finish(Answer.clarification(question))`; the question was written while understanding |
| `act_step.py` | `Actor`, `ToolCatalog` | `turn.drafted(draft)` |
| `run_tools_step.py` | `ToolExecutor` | runs every call of the last draft **in parallel** (`asyncio.gather`), `turn.observed(results)` |
| `review_step.py` | `Reviewer` | `turn.reviewed(verdict)`; unreadable → accept |
| `feedback_step.py` | none | `turn.give_feedback(critique)` |
| `finish_step.py` | none | `turn.finish(turn.conclude())` if no answer yet, then `conversation.close(turn)` |
| `summarize_step.py` | `Summarizer`, `TokenCounter` | when the history is long, `conversation.compact(summary, keep_last=4)` |

**`application/port/inbound/`** — how the outside calls the application

| File | Contents |
|---|---|
| `agent_request.py` | `AgentRequest(message, model_name, request_id, auto_approve)` |
| `handle_message_port.py` | `HandleMessagePort` protocol, what the controller depends on |

**`application/port/outbound/`** — what the application needs from the outside

| File | Port | Implemented by |
|---|---|---|
| `intent_classifier.py` | `IntentClassifier.understand` | `LangChainIntentClassifier` |
| `planner.py` | `Planner.plan` | `LangChainPlanner` |
| `actor.py` | `Actor.act` | `LangChainActor` |
| `reviewer.py` | `Reviewer.review` | `LangChainReviewer` |
| `summarizer.py` | `Summarizer.summarize` | `LangChainSummarizer` |
| `token_counter.py` | `TokenCounter.count` | `EstimatedTokenCounter` |
| `tool_catalog.py` | `ToolCatalog.tools` | `Toolbox` |
| `tool_executor.py` | `ToolExecutor.run` | `Toolbox` |
| `model_registry.py` | `ModelRegistry.turn_settings` | `ModelCatalog` |
| `workflow_runner.py` | `WorkflowRunner.run` | `LangGraphWorkflowRunner` (and `InMemoryWorkflowRunner` in tests) |
| `turn_event_stream.py` | `TurnEventStream.publish / complete / __aiter__` | `QueueTurnEventStream` |

### 2.6 `src/agent_orchestrator/adapter/` — technology

**`adapter/inbound/web/`** — HTTP in, SSE out

| File | Contents |
|---|---|
| `controller/stream_agent_controller.py` | `StreamAgentController.execute`: admission control (semaphore, 503 when full), starts the use case as a background task, returns a `StreamingResponse` whose generator reads events and presents them; cancels the task when the client leaves |
| `sse_presenter.py` | `SsePresenter`: the only place that decides wording and SSE shape. `STEP_STATUS` texts, `Running <tools>`, the final frame with metadata, `complete`, `error` |
| `schema/agent_request_schema.py` | `AgentRequestSchema` (pydantic): validates the JSON body; `to_domain()` → `AgentRequest` |
| `schema/agent_message_schema.py` | `AgentMessageSchema`: the final frame (`session_id`, `content`, `metadata`, `error`, `message_status`, `message_type`); `serialize()` → `event: …\ndata: …\n\n` |
| `schema/agent_message_stream_schema.py` | `AgentMessageStreamSchema(type, content)`: status, token, error and complete frames |
| `schema/message_stream_type.py` | `MessageStreamType`: `token`, `status`, `final`, `error`, `complete` |
| `schema/agent_message_type.py` | `AgentMessageType`: `text` (others reserved) |

**`adapter/outbound/event/`**

| File | Contents |
|---|---|
| `queue_turn_event_stream.py` | `QueueTurnEventStream`: an `asyncio.Queue` per request; the use case puts events in, the HTTP response takes them out; `None` marks the end |

**`adapter/outbound/langgraph/`** — the workflow engine (section 6)

| File | Contents |
|---|---|
| `langgraph_workflow_runner.py` | `LangGraphWorkflowRunner.run`: loads the stored conversation, starts the graph, forwards node events, yields `finished` at the end; sets `thread_id` and `recursion_limit` |
| `graph/agent_graph_builder.py` | `AgentGraphBuilder.build`: one node per step, edges from `TurnPolicy.targets`, compiled with the checkpointer |
| `graph/policy_router.py` | `PolicyRouter.after(step)`: the function for a conditional edge (decode the turn, ask `policy.next`); `node_name` (`Step.END` → LangGraph's `END`) |
| `node/agent_node.py` | `AgentNode`: decode state → emit `step_started` → `handler.run` → encode state. Subclasses override `work` only to use a LangGraph feature |
| `node/agent_nodes.py` | `NODE_TYPES` (one class per step) and `agent_nodes(handlers, codec)`: pairs each node class with its handler |
| `node/understand_node.py` … `node/summarize_node.py` | Nine one-line subclasses (`UnderstandNode`, `PlanNode`, `ClarifyNode`, `ActNode`, `RunToolsNode`, `ReviewNode`, `FeedbackNode`, `FinishNode`, `SummarizeNode`), each sets `step` |
| `state/graph_state.py` | `GraphState`: `{"conversation": dict, "turn": dict}`, the JSON LangGraph stores |
| `state/turn_state_codec.py` | `TurnStateCodec`: domain objects ⇄ JSON with pydantic `TypeAdapter`s; `stored_conversation` returns `None` for an unreadable (older-format) checkpoint |

**`adapter/outbound/llm/`** — models (section 8)

| File | Contents |
|---|---|
| `model_catalog.py` | `AgentRole` (the five roles = operation names in `agent.yml`) and `ModelCatalog`: selectable models by name, frozen roles, `settings_for(role, model)`, `turn_settings(model)` |
| `mapper.py` | `ModelSettingsMapper`: a config operation → `(ModelConnector, ModelParameters)`; API key from the connector's token, `No_Key` for keyless local servers |
| `schema.py` | `ModelConnector(base_url, api_key)`, `ModelParameters(model_name, temperature, max_output_tokens, max_context_tokens, max_iterations, use_streaming, max_reflection_retries, reasoning_effort)` |
| `thinking.py` | `thinking_switch`: `chat_template_kwargs.enable_thinking`, which turns Qwen thinking on or off per request in llama.cpp |
| `enum/reasoning_effort.py` | `ReasoningEffort`: `low`, `medium`, `high` |
| `langchain/chat_factory.py` | `LLMChat.create_chat_client`: a `ChatOpenAI` with the parameters, the shared HTTP client, `max_retries=0` (retries live in the HTTP transport) |
| `langchain/chat_models.py` | `ChatModels.for_role(role, model)`: one cached client per (server, parameters); streaming forced off |
| `langchain/context_window.py` | `ContextWindow.build`: system prompt (+ summary) + the most recent history that fits the budget + the tail; `history` (trim from the end, start on a user message) |
| `langchain/messages.py` | Translation: history → LangChain messages, turn work → AI/Tool/Human messages, model reply → `Draft`, `render` (history as text) |
| `langchain/model_call.py` | `invoke` (retryable model error → `AgentUnavailableException`), `invoke_structured` (JSON output parsed into a pydantic model, `None` if unreadable) |
| `langchain/dto.py` | `UnderstandingDto`, `VerdictDto`: the JSON schemas the context and review models must fill, with `to_domain()` |
| `langchain/intent_classifier.py` | `LangChainIntentClassifier` (role `agent_context`) |
| `langchain/planner.py` | `LangChainPlanner` (role `agent_plan`) |
| `langchain/actor.py` | `LangChainActor` (role `agent_act`): binds tools only under a plan; turns a `NEEDS_PLAN:` line into `Draft.asking_for_plan` |
| `langchain/reviewer.py` | `LangChainReviewer` (role `agent_reflection`): clips evidence (2 000 chars) and messages (4 000 chars) |
| `langchain/summarizer.py` | `LangChainSummarizer` (role `agent_summary`) |
| `langchain/token_counter.py` | `count_tokens` (cheap estimate: words + punctuation runs), `EstimatedTokenCounter` |
| `langchain/prompts/context.py` | The classification prompt: the ordered intent checklist and the output JSON |
| `langchain/prompts/plan.py` | The plan prompt: `## Plan` / `## Expected result` shape, revision block |
| `langchain/prompts/act.py` | The act prompt: execute mode (plan + how to use tools) or direct mode (no tools; `NEEDS_PLAN:` line); `act_feedback`; `plan_request` parser |
| `langchain/prompts/review.py` | The review prompt: accept / retry rules |
| `langchain/prompts/summary.py` | The running-summary prompt (≤ 200 words) |
| `langchain/prompts/tool_catalog.py` | `- name: description` lines, or "(no tools are available right now)" |
| `langchain/prompts/clock.py` | `utc_now()` for the prompts |

**`adapter/outbound/tool/`** — tools (section 9)

| File | Contents |
|---|---|
| `toolbox.py` | `Toolbox`: implements `ToolCatalog` and `ToolExecutor`; an unknown tool or a crash becomes a failed `ToolResult`, never an exception |
| `tool_registry.py` | `ToolRegistry`: tools by name |
| `tool_port.py` | `ToolPort` (one tool: `specification`, `invoke`) and `ToolProviderPort` |
| `mcp/mcp_session_factory.py` | `McpSessionFactory` protocol |
| `mcp/streamable_http_session_factory.py` | Opens an MCP session (streamable HTTP or SSE), 3 attempts with backoff, adds `X-Request-ID` and auth headers |
| `mcp/mcp_tool_provider.py` | `McpToolProvider.tools`: `list_tools` on the server → `McpTool`s |
| `mcp/mcp_tool.py` | `McpTool.invoke`: opens a session, `call_tool`, structured content as JSON or text blocks joined; errors → failed result |

### 2.7 `src/bootstrap/` — composition root

| File | Contents |
|---|---|
| `application/agent_application.py` | `create_agent_application()`: FastAPI app, middlewares (request id, request context, CORS `*`), lifespan (boot the container, include routers, stop on shutdown); `app` is what uvicorn loads |
| `configuration/settings.py` | `ProcessSettings.for_role`: env vars `CONFIGURATION_DIR` (`./config`), `APP_ENV` (`debug`), `LOG_LEVEL` (`INFO`), `MAX_CONCURRENT_STREAMS` (`200`) |
| `configuration/application_configuration.py` | `SetApplicationConfiguration`: loads the YAML with pycraftcore |
| `configuration/application_logger.py` | `create_logger`: a default logger when none is given |
| `container/container.py` | `Container` protocol (logging, configuration, boot, stop) |
| `container/agent_container.py` | `AgentContainer(AgentDI)`: `boot` (HTTP transport, factories, routers), `stop` (close everything), builds the stream router and the actuator router |
| `di/base_di.py` | `BaseDI`: logger, configuration, telemetry provider, client/repository registration and shutdown |
| `di/agent_di.py` | `AgentDI`: wiring only. MCP factories and tool discovery, LLM HTTP transport (retry + circuit breaker), `ModelCatalog`, `ChatModels`, checkpointer (MongoDB, else SQLite), the nine steps, the graph, the runner, `HandleMessage` |
| `router/agent/stream_agent_router.py` | `POST /v1/stream` → `controller.execute` |
| `router/actuator/actuator_router.py` | `GET /actuator/health`, `/health/liveness`, `/health/readiness`, `/info` |
| `router/actuator/enum/status.py` | `HealthStatus`: `UP`, `DOWN` |
| `router/actuator/schema/response.py` | `HealthSchema`, `InfoSchema` |

### 2.8 `sandbox/` — notes (not in git)

| Path | What it is |
|---|---|
| `readme_freeze.md` | This guide |
| `readme_interne.md` | The shorter internal guide: layers, policy table, how-tos, changelog |
| `design_clean_architecture.md` | The design written before the rewrite (now implemented) |
| `changed_freeze.md` | Running list of every changed file across the five repos (cumulative) |
| `archive/` | Guides of earlier designs (Claude SDK engine, engine comparison, first LangGraph engine). History only |
| `change.md`, `files*.md`, `sum.txt`, `cvg.png`, `try_nvidia_provider.py` | Scratch files: test inputs, file lists, a provider experiment |

---

## 3. The objects you need to know

### 3.1 Lifetimes

| Object | Created | Lives | Stored? |
|---|---|---|---|
| `AgentContainer`, `ModelCatalog`, `ChatModels`, `Toolbox`, step handlers, nodes, compiled graph, `HandleMessage`, `StreamAgentController` | once, at boot | until shutdown | no |
| `AgentRequestSchema` → `AgentRequest` | per HTTP request | the request | no |
| `QueueTurnEventStream` | per HTTP request | the request | no |
| `Turn` | per HTTP request, in `HandleMessage` | the request (in LangGraph: re-created from JSON at every step) | yes, the last turn sits in the checkpoint, overwritten by the next one |
| `Conversation` | first message of a `request_id`, then loaded from the checkpoint | across messages, until the checkpoint expires | yes |
| `TurnEvent` | per step, plus one `finished` | until presented | no |

### 3.2 `Conversation`: what survives between messages

```
Conversation
├── id             = request_id sent by the UI (= LangGraph thread_id)
├── messages       [Message(user, "…"), Message(assistant, "…"), …]  only user text + final answer
├── summary        "…"  running summary of messages folded away by summarize
└── pending_plan   Plan | None  a plan shown to the user and waiting for "yes"
```

Tool results, drafts and critiques are **not** kept in `messages`. Only what the user wrote
and the answer they got. The next turn sees history, not the previous turn's work.

### 3.3 `Turn`: everything about one message

```
Turn
├── request        the raw user message ("yes", "explain change.md")
├── model          model_name from the request
├── settings       TurnSettings  ← agent_act parameters (max_steps 20, max_retries 2, …)
├── options        TurnOptions   ← request (auto_approve)
├── understanding  Understanding ← understand step (intent, standalone query, criteria, question)
├── plan           Plan | None   ← set only when the plan is being carried out in this turn
├── work           [Draft, ToolResult, ToolResult, Draft, Feedback, Draft, …]  in order
├── verdicts       [Verdict, …]  ← review step
└── answer         Answer | None ← clarify / plan (approval request) / finish
```

Derived values the policy relies on:

| Question | Computed as |
|---|---|
| `query` | `understanding.query`, else `request` |
| `intent` | `understanding.intent`, else `None` |
| `steps_taken` | number of `Draft`s in `work` (one per act call) |
| `retries` | number of `Feedback`s in `work` |
| `evidence` | the `ToolResult`s in `work` |
| `used_tools` | any evidence |
| `last_draft` / `last_verdict` | the latest of each |
| `is_plain_direct_answer` | intent is `direct` and no tool was used |

`Turn.execute(plan)` sets the plan **and clears `work` and `verdicts`**. What was drafted before
the plan was approved (for example a "NEEDS_PLAN" draft) is not part of carrying it out, so
`steps_taken` starts again at 0.

`Turn.conclude()` turns the work into an answer when nothing set one earlier:

| Situation | Answer | Outcome |
|---|---|---|
| no draft at all | "No answer was produced." | `best_effort` |
| last draft still asks for tools (budget spent) | "I reached the step limit…" | `budget_exhausted` |
| last verdict rejected it (retries spent) | the draft text | `best_effort` |
| otherwise | the draft text | `answered` |

### 3.4 Small value objects

- **`Understanding`**: the classifier's reading. `normalized()` fixes impossible readings:
  `plan_approval` with nothing pending becomes `direct`; `ambiguous` without a question becomes
  `task`.
- **`Plan(task, steps)`**: `task` = the standalone query; `steps` = the Markdown from the plan
  model.
- **`Draft(text, tool_calls, plan_request)`**: one act-model reply. Has either tool calls, or a
  plan request (`NEEDS_PLAN`), or just text.
- **`ToolResult`**: output or error of one call.
- **`Feedback(critique)`**: reviewer's critique, given to the next act call.
- **`Verdict(action, critique)`**: `accept` or `retry`.
- **`Answer(text, outcome)`**: what the user finally sees.
- **`TurnEvent`**: `step_started(step, tools)`, `finished(answer, steps_taken, max_steps,
  stream_answer)`, `failed(error)`.

---

## 4. Boot: what exists before the first request

`uvicorn bootstrap.application.agent_application:app` imports the module, which runs
`create_agent_application()`:

1. `ProcessSettings.for_role("agent-orchestrator")` reads env vars (`.env` loaded first).
2. `AgentContainer(settings)` is created. Nothing is connected yet: every dependency is a
   `cached_property`, built the first time it is used.
3. Middlewares are added: `RequestIDMiddleware`, `RequestMiddleware` (puts the Starlette request
   in a context variable), `CORSMiddleware` (everything allowed).

Then FastAPI runs the **lifespan** → `container.boot()`:

```
boot()
├── _llm_transport_factory         resilient HTTP transport to the LLM server
│     ├── _configuration           YAML loaded (connectors + operations)
│     ├── _logging                 standard logging at LOG_LEVEL
│     └── _telemetry_provider      OpenTelemetry tracer + log handler
├── _start_factories()
└── _create_routers()
      ├── _stream_agent_router()
      │     └── _handle_message()
      │           ├── _toolbox()                     MCP tool discovery (section 9)
      │           │     for "toolbox" + every "external_mcp_*" connector:
      │           │       McpToolProvider.tools() → list_tools → McpTool per tool
      │           │       a server that is down is skipped with a warning
      │           ├── _checkpointer()                MongoDB ping ok → MongoDBSaver(ttl)
      │           │                                  else → AsyncSqliteSaver
      │           ├── _workflow_runner()
      │           │     └── _agent_graph()
      │           │           TurnStateCodec, TurnPolicy
      │           │           _steps(toolbox) → 9 step handlers with their LangChain adapters
      │           │           agent_nodes(...) → 9 AgentNode subclasses
      │           │           AgentGraphBuilder(...).build(checkpointer) → compiled graph
      │           │     LangGraphWorkflowRunner(graph)
      │           └── HandleMessage(runner, _model_catalog, logger)
      │       StreamAgentController(handle_message, QueueTurnEventStream, logger, 200)
      │       StreamAgentRouter(controller)  → POST /v1/stream
      └── _actuator_router()                         → /actuator/*
```

The routers are included into the app. From now on the same graph, handlers and model clients
serve every request. They hold no per-request state. All per-request state is in the `Turn`,
the `Conversation` and the checkpoint.

The log at boot shows: configuration loaded, `Discovered N MCP tools from 'toolbox': …`,
`Using MongoDB checkpointer with TTL` (or SQLite), `Router /v1 included`, `Agent container
booted`.

---

## 5. Walkthrough: from the request to the final answer

The example is the second message of a conversation: the user says **"explain change.md"**
with auto-approve **off**, then **"yes"**. Each stage names the code, the objects created and
what changes.

### Stage 1: the browser sends the request (homelab-ui)

`AgentStore.dispatch(text)` (`homelab-ui/src/app/features/agent/application/agent.store.ts`):

- adds two bubbles to `messages`: the user's text and an empty assistant bubble with
  `streaming: true`;
- creates an `AbortController` (the Stop button);
- calls `AgentApiService.stream(body, signal)`, which sends:

```http
POST /api/v1/stream
Content-Type: application/json

{"message": "explain change.md", "model_name": "qwen3-1.7b",
 "request_id": "6f0c…-uuid", "auto_approve": false}
```

`/api` is stripped by the proxy (nginx in production, `proxy.conf.json` in dev), so the backend
receives `POST /v1/stream`.

### Stage 2: FastAPI validates the body

`StreamAgentRouter._stream` receives an **`AgentRequestSchema`** (pydantic). `message` must be
non-empty; `auto_approve` defaults to `false`. A bad body is a `422` before any agent code runs.

### Stage 3: the controller admits the request and starts the use case

`StreamAgentController.execute(request)`:

1. `request_id_context.set(request.request_id)`: every log line of this request carries it
   (the UUID column in the logs), and MCP calls send it as `X-Request-ID`.
2. Admission: if 200 streams are already running, `503 Server is at capacity`.
3. Creates **`events = QueueTurnEventStream()`**: an empty `asyncio.Queue`.
4. `request.to_domain()` → **`AgentRequest`** (plain dataclass).
5. Starts **`asyncio.create_task(use_case.handle(agent_request, events))`**. The use case now
   runs in the background.
6. Returns a **`StreamingResponse`** (`text/event-stream`) at once. Its body is
   `_event_generator`, which reads `events` and writes SSE frames. Log: `stream request
   accepted`, then uvicorn's `POST /v1/stream 200`. The 200 is sent before any model is called.

From here two coroutines run side by side:

```
use-case task:   HandleMessage.handle ── publish(event) ──►  Queue  ──► _event_generator ──► HTTP body
                                                                       (SsePresenter)
```

### Stage 4: the use case creates the Turn

`HandleMessage.handle(request, events)`:

```python
turn = Turn(
    request="explain change.md",
    model="qwen3-1.7b",
    settings=catalog.turn_settings("qwen3-1.7b"),   # raises UnknownModelException if unknown
    options=TurnOptions(auto_approve=False),
)
```

`turn_settings` checks the model is selectable, then reads the **`agent_act`** parameters:
`max_steps=20`, `max_retries=2`, `context_tokens=16384`, `stream_answer=True`.

Then `async for event in workflow.run(request.request_id, turn): await events.publish(event)`.

### Stage 5: the runner loads the conversation and starts the graph

`LangGraphWorkflowRunner.run(conversation_id, turn)`:

1. `config = {"configurable": {"thread_id": request_id}, "recursion_limit": 10 + 2×20 + 3×2 = 56}`.
2. `_load`: `graph.aget_state(config)` reads the latest checkpoint of this thread.
   - none → `Conversation(id)` (new conversation);
   - readable → the stored **`Conversation`** (messages, summary, pending plan);
   - unreadable (older format) → new conversation, with a warning.
3. `codec.encode(conversation, turn)` → **`GraphState`**: `{"conversation": {...json...},
   "turn": {...json...}}`. This becomes the input of the graph run. It **replaces** both keys
   of the stored state: the stored conversation comes back in (it was just loaded), and the
   previous turn is replaced by the new one.
4. `graph.astream(state, config, stream_mode=["custom", "values"])`:
   - `custom` chunks are the `TurnEvent`s nodes emit → yielded to `HandleMessage`;
   - `values` chunks are the full state after each step → the last one is kept as `final`.

### Stage 6: each node runs one step

Every node does the same thing (`AgentNode.__call__`):

```
state (JSON) ─► codec.decode ─► Conversation, Turn  (new Python objects)
             ─► emit TurnEvent.entering(step, turn)  → custom stream → queue → SSE "status"
             ─► handler.run(conversation, turn)      (the application step, mutates both)
             ─► codec.encode ─► new state (JSON)     → LangGraph saves a checkpoint
```

After the node, LangGraph follows the edge. A plain edge has one target. A conditional edge
calls `PolicyRouter.after(step)`, which decodes the turn and asks `TurnPolicy.next(step,
turn)`.

For "explain change.md" (auto-approve off):

**① understand** (`UnderstandStep`)
- SSE: `status: Understanding your request`.
- `LangChainIntentClassifier.understand`: system prompt = classification checklist + JSON
  schema; user message = history rendered as text + pending plan (none) + the message.
  Log: `Calling the context model`.
- Reply parsed into `UnderstandingDto` → `Understanding(intent=task, query="Explain the file
  change.md", success_criteria=(…))`.
- `conversation.interpret(turn, understanding)`: normalised, no pending plan, `task` does not
  keep one → `turn.understood(understanding)`. Log: `Understood: Understanding(...)`.
- Router: `needs_plan` (task) → **plan**.

**② plan** (`PlanStep`)
- SSE: `status: Preparing a plan`.
- `LangChainPlanner.plan`: system prompt = task + tool catalog + plan shape; context window =
  history that fits + the user message. Log: `Calling the plan model`.
- `Plan(task="Explain the file change.md", steps="## Plan\n1. Read change.md (tool:
  file_reader)\n## Expected result\n…")`.
- `conversation.submit(turn, plan)`: auto-approve off → `conversation.pending_plan = plan`,
  `turn.answer = Answer.approval_request(plan)` (the plan + "Reply **yes** to run this plan…",
  outcome `awaiting_approval`).
- Router: `has_approved_plan`? `turn.plan` is `None` → no → **finish**.

**③ finish** (`FinishStep`): answer already set, so `conversation.close(turn)` appends
`Message(user, "explain change.md")` and `Message(assistant, "<plan + Reply yes…>")`.
Plain edge → **summarize**.

**④ summarize** (`SummarizeStep`): 4 messages or fewer, or fewer tokens than half of
`context_tokens` → nothing. Plain edge → **END**.

### Stage 7: the final event and the stream end

- The graph stops. The last `values` chunk is decoded → `TurnEvent.finished(turn)` with
  `answer`, `steps_taken=0`, `max_steps=20`, `stream_answer=True`.
- `HandleMessage` publishes it, then `finally: events.complete()` puts `None` in the queue.
- `_event_generator` presents `finished` as two frames (because `stream_answer`): a `token`
  frame with the whole answer, then a `final` frame with metadata. Then the queue ends and it
  writes `complete`. The semaphore slot is released.

What the browser receives:

```
event: status
data: {"type":"status","content":"Understanding your request"}

event: status
data: {"type":"status","content":"Preparing a plan"}

event: token
data: {"type":"token","content":"## Plan\n1. Read change.md (tool: file_reader)\n…Reply **yes**…"}

event: final
data: {"session_id":"6f0c…","content":"## Plan\n…","metadata":{"iteration":"0","max_iteration":"20","outcome":"awaiting_approval"},"error":null,"message_status":"final","message_type":"text"}

event: complete
data: {"type":"complete","content":""}
```

### Stage 8: what is stored now

The checkpoint of thread `6f0c…` holds:

```json
{
  "conversation": {
    "id": "6f0c…",
    "messages": [ …earlier…, {"speaker":"user","text":"explain change.md"},
                  {"speaker":"assistant","text":"## Plan …Reply **yes**…"} ],
    "summary": "",
    "pending_plan": {"task": "Explain the file change.md", "steps": "## Plan …"}
  },
  "turn": { "request": "explain change.md", "understanding": {...}, "plan": null,
            "work": [], "verdicts": [], "answer": {...awaiting_approval...}, … }
}
```

LangGraph wrote one checkpoint per step (understand, plan, finish, summarize). The latest is
what the next message loads.

### Stage 9: the user replies "yes"

A new request with the same `request_id`. Stages 1–5 repeat. The loaded conversation now has
`pending_plan`.

**① understand**: the classifier sees the pending plan in its prompt → `plan_approval`.
`conversation.interpret`: approval + pending plan → `turn.understood(understanding.about(plan.task))`
(the query becomes the plan's task), `turn.execute(plan)` (plan into the turn, work cleared),
`conversation.pending_plan = None`. Router: not `needs_plan`, not ambiguous → **act**.

**② act** (`ActStep`, no status shown)
- `LangChainActor.act`: plan present → **execute mode** prompt (plan steps + how to use tools);
  tools bound to the model; messages = system + history that fits + `Human("yes")` + work so
  far (none). Log: `Calling the act model (step 1)`.
- Reply has tool calls → `Draft(text="", tool_calls=(ToolCall(id="call_ab12cd34",
  name="file_reader", arguments={"file_path": "change.md"}),))` → `turn.drafted(draft)`.
- Router: out of steps? 1 < 20, no. `asks_for_tools` → **run_tools**.

**③ run_tools** (`RunToolsStep`)
- SSE: `status: Running file_reader`.
- `Toolbox.run(call)` → `McpTool.invoke` → new MCP session (log: `MCP session established on
  …/mcp`) → `call_tool` → `ToolResult(call_id, "file_reader", output="{…json…}")`.
- `turn.observed([result])`. Plain edge → **act**.

**④ act** again: messages now end with `AI(tool_calls)` + `Tool(result)`. Log: `Calling the
act model (step 2)`. Reply is text → `Draft(text="change.md lists …")`. Router: no tools asked;
`is_plain_direct_answer`? Intent is `plan_approval`, so no → **review**.

**⑤ review** (`ReviewStep`)
- SSE: `status: Checking the answer`.
- `LangChainReviewer.review`: last 2 history messages + "yes", the interpreted request,
  success criteria, the plan, the tool evidence (clipped), the answer. Log: `Calling the
  reflection model`. → `Verdict(accept)`.
- Router: `retry_allowed`? not a rejection → **finish**.

**⑥ finish**: no answer yet → `turn.conclude()` → `Answer.answered("change.md lists …")`;
`conversation.close` appends `"yes"` and the answer. **⑦ summarize** → END.

UI gets: `status Understanding…`, `status Running file_reader`, `status Checking the answer`,
`token`, `final` (`iteration 2`, `outcome answered`), `complete`.

### Stage 10: the same request with auto-approve on

With `auto_approve: true` the first message does everything in one turn. `conversation.submit`
calls `turn.execute(plan)` instead of proposing it. No pending plan, no approval answer. Then
`has_approved_plan` is true and the graph goes plan → **act**. From there it is identical to
stage 9 ②–⑦. The stored history has one exchange: `"explain change.md"` → the final answer.

---

## 6. How the plain steps and LangGraph work together

### 6.1 The division of work

| Concern | Who owns it | Where |
|---|---|---|
| What a step does | the step handler | `application/step/*_step.py` |
| Which step comes next | the policy | `domain/workflow/turn_policy.py` + `conditions.py` |
| Running steps in order, storing state, streaming events, limits | LangGraph | `adapter/outbound/langgraph/` |
| Calling models and tools | LangChain / MCP adapters behind ports | `adapter/outbound/llm`, `adapter/outbound/tool` |

The step handlers do not know LangGraph exists. They take `(Conversation, Turn)` and mutate
them. LangGraph does not know what a step means: it calls nodes and follows edges. The nodes
and the router are the thin glue between the two.

### 6.2 The glue, piece by piece

```
             ┌──────────────── built once at boot ────────────────────┐
TurnPolicy ──┤ AgentGraphBuilder                                       │
 .targets()  │  for each node: add_node(name, node)                    │
             │  START → understand                                     │
             │  one target  → add_edge(node, target)                   │
             │  many        → add_conditional_edges(node,              │
             │                    PolicyRouter.after(step), targets)   │
             │  compile(checkpointer)                                  │
             └─────────────────────────────────────────────────────────┘

             ┌──────────────── at every step ─────────────────────────┐
GraphState ─►│ AgentNode.__call__                                      │
  (JSON)     │   decode → (Conversation, Turn)                         │
             │   emit TurnEvent.entering(step)                         │
             │   work() → StepHandler.run(conversation, turn)          │
             │   encode → GraphState  ─► checkpoint saved              │
             │ PolicyRouter.after(step)(state)                         │
             │   decode turn → TurnPolicy.next(step, turn) → node name │
             └─────────────────────────────────────────────────────────┘
```

- **`TurnStateCodec`** is the bridge between domain objects and the JSON LangGraph stores. It
  uses pydantic `TypeAdapter`s over the domain dataclasses, so the domain needs no pydantic.
  The `kind` literal on `Draft`, `ToolResult` and `Feedback` tells the three work items apart
  when decoding.
- **`AgentNode`** subclasses exist one per step (`ActNode`, …). Today they all just delegate.
  They are the place to add LangGraph-only features later (an `interrupt` for approval, a
  `Send` fan-out, a subgraph) by overriding `work`, without touching the application.
  `AgentNode` refuses a handler of another step (`ValueError` at boot).
- **`AgentGraphBuilder`** draws edges from `TurnPolicy.targets()`, so the graph can't
  drift from the rules. Today that is 17 edges: START → understand, 5 plain edges (clarify,
  run_tools, feedback, finish, summarize) and 11 conditional targets (understand 3, plan 2,
  act 4, review 2). `test_agent_graph.py` checks the compiled edges equal the policy.
- **`PolicyRouter`** is the only routing logic in the graph, and it just asks the policy.

The generated graph:

```
__start__ ──► understand
understand ─ ─► plan | clarify | act          (conditional)
plan       ─ ─► act | finish                  (conditional)
clarify    ───► finish
act        ─ ─► plan | finish | run_tools | review   (conditional)
run_tools  ───► act
review     ─ ─► feedback | finish             (conditional)
feedback   ───► act
finish     ───► summarize
summarize  ───► __end__
```

### 6.3 What LangGraph adds

1. **Persistence.** The checkpointer saves the state after every step under `thread_id =
   request_id`. That is how the conversation survives between messages (section 10).
2. **Streaming.** Nodes write `TurnEvent`s with `get_stream_writer()`. The runner reads them
   in `custom` mode while the graph runs, so the UI sees "Running file_reader" while the tool
   runs, not afterwards.
3. **A safety limit.** `recursion_limit` (56 with the current config) stops a runaway loop
   even if the policy had a bug. The policy's own limits (`max_steps`, `max_retries`) end
   turns long before that.
4. **Room to grow.** Subgraphs, interrupts and parallel branches are LangGraph features the
   node classes are ready for.

### 6.4 The same steps without LangGraph

`tests/agent_orchestrator/application/fakes.py` has an **`InMemoryWorkflowRunner`**: the same
handlers and the same policy, driven by a 6-line loop, with conversations in a dict:

```python
step = FIRST_STEP
while step is not Step.END:
    yield TurnEvent.entering(step, turn)
    await self._steps[step].run(conversation, turn)
    step = self._policy.next(step, turn)
yield TurnEvent.finished(turn)
```

That loop **is** the workflow. LangGraph runs the same loop with storage and streaming added.
The scenario tests (`tests/agent_orchestrator/scenarios/test_turn_scenarios.py`) run every
scenario on **both** runners and require the same answers, events and stored conversation.
That proves LangGraph adds no behaviour of its own.

One practical difference: in the in-memory runner the same `Turn` object is mutated from step
to step. In LangGraph each node gets **fresh objects decoded from JSON**, and only what is in
the state survives between steps. Anything a step wants the next step to see must be a field
of `Turn` or `Conversation`.

---

## 7. Routing: every possible path, with scenarios

### 7.1 The table

`TurnPolicy.TRANSITIONS`, read top to bottom; after a step, **the first row whose source
matches and whose condition holds** wins.

| # | After | Condition | Next |
|---|---|---|---|
| 1 | understand | `needs_plan`: intent is task or plan_revision, or there is no intent | plan |
| 2 | understand | `is_ambiguous` | clarify |
| 3 | understand | always (direct, continuation, plan_approval) | act |
| 4 | plan | `has_approved_plan`: `turn.plan` is set (auto-approved) | act |
| 5 | plan | always (plan proposed, waiting for "yes") | finish |
| 6 | clarify | always | finish |
| 7 | act | `asks_for_plan_without_one`: last draft says NEEDS_PLAN and the turn has no plan | plan |
| 8 | act | `asks_for_tools_out_of_steps`: tool calls but `steps_taken ≥ max_steps` | finish |
| 9 | act | `asks_for_tools` | run_tools |
| 10 | act | `is_plain_direct_answer`: intent direct and no tool used | finish |
| 11 | act | always | review |
| 12 | run_tools | always | act |
| 13 | review | `retry_allowed`: rejected, `retries < max_retries`, `steps_taken < max_steps` | feedback |
| 14 | review | always | finish |
| 15 | feedback | always | act |
| 16 | finish | always | summarize |
| 17 | summarize | always | end |

Row order matters: row 8 is checked before row 9, so a model that keeps calling tools is
stopped at the budget instead of looping.

### 7.2 What the context model can answer, and what the domain does with it

| Model says | Pending plan? | After `normalized` + `interpret` | Pending plan afterwards |
|---|---|---|---|
| task | any | task | dropped |
| plan_revision | yes | plan_revision | kept (the planner revises it) |
| plan_revision | no | plan_revision (plans from scratch) | — |
| ambiguous + question | any | ambiguous | kept |
| ambiguous, no question | any | **task** | dropped |
| plan_approval | yes | plan_approval, `turn.plan = pending`, query = plan task | consumed |
| plan_approval | no | **direct** | — |
| continuation | any | continuation | dropped |
| direct | any | direct | dropped |
| unreadable JSON | any | `fallback` → task | dropped |

### 7.3 Scenarios

Each line is the path of steps; **bold** marks the model calls. "Stored" is what the
conversation gains.

**S1. Plain direct question** ("what are the available tools?", "hi, my name is Toufik")
```
understand → act → finish → summarize → end
```
- **context** → direct. **act** in direct mode: no tools bound, the tool list is in the prompt,
  so "what tools do you have" is answered from it.
- Row 10: direct and no tool used → finish **without review** (nothing to check against).
- Stored: question + answer. Outcome `answered`. UI statuses: "Understanding your request".

**S2. Task, auto-approve off** ("how many users signed up today?")
```
understand → plan → finish → summarize → end
```
- **context** → task. **plan** → `conversation.propose`; answer = plan + "Reply yes".
- Stored: question + approval message; `pending_plan` set. Outcome `awaiting_approval`.

**S3. Approval of a pending plan** ("yes", "go", "ok do it")
```
understand → act → run_tools → act → … → review → finish → summarize → end
```
- **context** sees the pending plan → plan_approval. The plan moves into the turn.
- **act** in execute mode with tools bound → tool calls → run_tools → **act** reads results →
  … → text answer → **review**.
- Stored: "yes" + answer; `pending_plan` cleared.

**S4. Task, auto-approve on**
```
understand → plan → act → run_tools → act → … → review → finish → summarize → end
```
- `conversation.submit` executes the plan at once (row 4). One turn, no "yes" needed. Nothing
  pending is stored.

**S5. A task misread as direct, auto-approve off** (the classifier says direct, but the answer
needs a tool)
```
understand → act → plan → finish → summarize → end
```
- **act** in direct mode cannot run tools, so it replies `NEEDS_PLAN: <reason>`. The actor
  turns that into `Draft.asking_for_plan(reason)`.
- Row 7 → **plan** → proposed, answer = approval request. Same result as S2, one act call
  later. This recovery path is what keeps a misclassification from ending in "I would need a
  tool".

**S6. A task misread as direct, auto-approve on** (the log you sent on 2026-10-02)
```
understand → act → plan → act → run_tools → act → review → finish → summarize → end
```
- As S5, then row 4: the plan is executed in the same turn. `execute` clears the NEEDS_PLAN
  draft, so the log shows `act model (step 1)` twice.
- Review runs because tools were used.
- Edge case: if the act model answered **without** calling any tool after the plan, the intent
  is still `direct` and no tool was used. Row 10 would then finish without review.

**S7. Plan revision** ("use the csv instead", "add a step to save it")
```
understand → plan → finish → summarize → end
```
- **context** → plan_revision; the pending plan is kept. **plan** gets "The user asked to
  change this previous plan" + the old steps → new plan proposed (or executed if auto-approve).

**S8. Ambiguous message** ("and the other one?" with nothing to resolve it)
```
understand → clarify → finish → summarize → end
```
- **context** → ambiguous with a `clarification_question`. clarify makes it the answer (no
  model call). A pending plan is kept, so the user can still answer "yes" next.
- Outcome `clarification`. If the model said ambiguous but wrote no question, the domain
  treats it as a task (S2).

**S9. Continuation** ("shorter", "as a table")
```
understand → act → review → finish → summarize → end
```
- **act** in direct mode reworks the previous answer from history. Not `direct`, so it **is**
  reviewed (row 11).

**S10. Rejected answer, retried**
```
… act → review → feedback → act → review → finish …
```
- **review** returns `retry` with a critique. Row 13 if `retries < 2` and steps are left.
- feedback appends `Feedback(critique)`; the next **act** sees "A reviewer rejected your last
  answer. Critique: … Fix only what the critique flags."
- After 2 retries, row 14 → finish; `conclude` gives the last draft as `best_effort`.

**S11. Out of steps**
```
… act → run_tools → act → run_tools → … → act → finish …
```
- Every act call is a step. When a draft still asks for tools and `steps_taken ≥ 20`, row 8 →
  finish; `conclude` → "I reached the step limit…", outcome `budget_exhausted`.

**S12. Unreadable outputs**
- Context JSON unreadable → `Understanding.fallback` → task → plan (warning logged). A plan to
  approve is the safe default.
- Review JSON unreadable → accept (warning logged). A broken judge never blocks the answer.

**S13. Moving on from a pending plan**: the user ignores the plan and asks something else
(task, direct, continuation) → the pending plan is dropped. A later "yes" is read as direct
(nothing pending).

**S14. Approval with nothing pending** ("yes" out of the blue) → normalised to direct → S1.

**S15. Long conversation**: on every turn summarize checks: more than 4 messages **and**
estimated tokens > `context_tokens / 2` (8 192 with 16 384) → **summary** model merges the old
summary with all but the last 4 messages → `conversation.compact`. If the summary call fails,
the history is kept as is. The answer has already been given by then.

### 7.4 Which model calls each path makes

| Path | context | plan | act | review | summary |
|---|---|---|---|---|---|
| S1 direct | 1 | – | 1 | – | maybe |
| S2 task, propose | 1 | 1 | – | – | maybe |
| S3 approval | 1 | – | n+1 (n tool rounds) | 1 (+1 per retry) | maybe |
| S4 task, auto | 1 | 1 | n+1 | 1+ | maybe |
| S5 misread, propose | 1 | 1 | 1 | – | maybe |
| S6 misread, auto | 1 | 1 | n+2 | 1+ | maybe |
| S8 ambiguous | 1 | – | – | – | maybe |
| S9 continuation | 1 | – | 1 | 1+ | maybe |

---

## 8. Models: who is called, with what

### 8.1 Choosing the model

```
request.model_name ──► ModelCatalog
                        ├── models  {parameters.model of each llm.yml entry: settings}
                        └── roles   {AgentRole: settings}  only roles with parameters.model set
settings_for(role, model) = roles[role] if frozen, else models[model]
turn_settings(model)      = check model exists, then agent_act's parameters
```

- A role **frozen** in `agent.yml` always uses its model, whatever the UI selected.
- A role with `model: null` follows the UI's selection.
- With the current `agent.yml`, **all five roles are frozen to
  `nvidia/nemotron-3-super-120b-a12b`**. The UI's model dropdown is only checked for validity:
  every call goes to the frozen model (section 13).

`ChatModels.for_role` caches one `ChatOpenAI` per (server URL, parameters), with streaming
forced off. All clients share one HTTP client from pycraftcore's resilient transport: retries
(`retry` in `api.yml`, backoff 1–20 s) and a circuit breaker (`llm-gateway`: opens after 3
failures, 30 s recovery). `reasoning_effort: null` sends `enable_thinking: false` to the
server.

### 8.2 What each model sees

| Role | Prompt (system) | Messages | Output |
|---|---|---|---|
| **context** | intent checklist + JSON schema | one human message: history (trimmed to `context_tokens`, rendered as `User:/Assistant:` text), pending plan steps, the latest message | `UnderstandingDto` JSON |
| **plan** | task (standalone query) + previous plan if revising + tool catalog + plan shape + time | `ContextWindow`: system (+ summary), history that fits, the raw message | Markdown plan |
| **act** | request + tool catalog + **execute mode** (plan + how to work with tools) **or direct mode** (no tools; `NEEDS_PLAN:` rule) + time | system (+ summary), history that fits, the raw message, then the turn's work as AI (with tool calls) / Tool / Human (critique) messages | text, or tool calls (only under a plan) |
| **reflection** | accept/retry rules + JSON schema | one human message: last 2 history messages + latest, interpreted request, success criteria, plan, evidence (each clipped to 2 000 chars), answer | `VerdictDto` JSON |
| **summary** | "keep a running summary, ≤ 200 words" | old summary + the messages to fold | plain text |

`ContextWindow.build` reserves room for the system prompt and the tail first, then fills the
rest of `context_tokens` with the **most recent** history, starting on a user message. The
conversation summary is appended to the system prompt. Token counts are estimates
(`token_counter.py`), not the model's tokenizer.

### 8.3 Streaming of the answer

Models are never streamed token by token. When `use_streaming: true` on `agent_act`
(`TurnSettings.stream_answer`), the presenter sends the finished answer once as a `token`
frame before the `final` frame. The UI shows it, then replaces it with the `final` content
(the same text).

---

## 9. Tools

- **Discovery, at boot only.** For the `toolbox` connector and every `external_mcp_*`
  connector, `McpToolProvider` opens a session and calls `list_tools`. Each tool becomes an
  `McpTool` holding its `ToolSpecification`. A server that is down is skipped. Tools added to
  the server later need a restart of the orchestrator.
- **Catalog.** `Toolbox.tools()` gives every specification. The plan prompt and the act prompt
  list them (`- name: description`). The act model gets them **bound** (as callable functions)
  only when the turn has a plan.
- **Execution.** `RunToolsStep` runs every call of the last draft at the same time.
  `Toolbox.run` → `ToolRegistry.get(name)` → `McpTool.invoke`: **a new MCP session per call**
  (the `MCP session established … (attempt 1/3)` log line), `call_tool(name, arguments)`.
  Structured content is serialised as JSON, otherwise text blocks are joined.
- **Failures never raise.** Unknown tool, MCP error, unreachable server → a `ToolResult` with
  `error`. The act model sees `Error: …` as the tool message and can react.
- **Headers.** Each MCP request carries `X-Request-ID` (the conversation id) and the
  connector's auth.
- agent-toolbox runs Python in `python_executor`, where the other tools are callable as Python
  functions. The working directory is shared file storage. The act prompt explains both.

---

## 10. What is stored, where, for how long

| What | Where | Lifetime |
|---|---|---|
| Conversation + last turn | LangGraph checkpoints, MongoDB (`mongodb_checkpointer`), else SQLite (`sqlite_checkpointer`) | MongoDB: documents expire after `pool.ttl` (3 600 s). SQLite: no expiry |
| Key | `thread_id` = `request_id` = the UI's session id | — |
| One checkpoint | written after **every step** (understand, plan, act, …) | the latest is read when the next message arrives |
| UI chat bubbles | the browser's `AgentStore` (memory) | until page reload or "New session" |
| Logs, traces | stdout + OpenTelemetry (Loki/Tempo) | per collector config |

Notes:

- The backend history (`Conversation.messages`) and the UI bubbles are **separate**. The UI
  never sends history: the backend rebuilds it from the checkpoint by `request_id`.
- A page reload makes a new session id. The old conversation stays in MongoDB until its TTL.
- A checkpoint written by an older version of the state layout cannot be read. That
  conversation silently restarts empty (`stored_conversation` returns `None`, a warning is
  logged).
- The state also contains the full last `Turn`: tool outputs and drafts of the last message.
  It is replaced by the next message and never shown to the models as history.

---

## 11. How the frontend and the backend communicate

### 11.1 The path of a request

```
Browser (homelab-ui)                      nginx in the homelab-ui container            agent-orchestrator
fetch POST {baseUrl}/v1/stream  ───────►  location /api/ {                    ───────► POST /v1/stream
  baseUrl = "/api" (default,                proxy_pass http://agent-orchestrator:8000/;
  editable, kept in localStorage)           proxy_buffering off;  (frames go out at once)
                                            proxy_read_timeout 3600s; }
```

- In development, `ng serve` uses `proxy.conf.json`: `/api` → `http://localhost:8001`, with
  `/api` stripped. That only works if the orchestrator listens on 8001 locally (`make run` and
  the Docker image use 8000). Check that it matches your setup.
- CORS is open (`*`), so the UI can also point `baseUrl` straight at `http://host:8000`.

### 11.2 The request body

| Field | UI source | Backend use |
|---|---|---|
| `message` | the composer text | `Turn.request` |
| `model_name` | settings panel dropdown (`KNOWN_MODELS` in `domain/model-catalog.ts`) | must match a `parameters.model` in `llm.yml`; selects models for roles that are not frozen |
| `request_id` | `AgentStore.sessionId`: a UUID made at start or by "New session" | conversation id = LangGraph `thread_id`; also the log/trace request id |
| `auto_approve` | settings panel checkbox (`AgentStore.autoApprove`, default off) | `Turn.options.auto_approve` |

### 11.3 The response: Server-Sent Events over the POST response

`EventSource` can only send GET requests, so the UI reads the `fetch` body itself
(`AgentApiService.stream`). It splits frames on blank lines and parses `event:` and `data:`.

| Event | Sent when | `data` | UI does |
|---|---|---|---|
| `status` | a step starts: understand, plan, review, run_tools | `{"type":"status","content":"Preparing a plan"}` | shows it above the bubble while streaming |
| `token` | turn finished and `stream_answer` | `{"type":"token","content":"<whole answer>"}` | appends to the bubble |
| `final` | turn finished | `{"session_id","content","metadata":{"iteration","max_iteration","outcome"},"error","message_status","message_type"}` | replaces the bubble content, clears the status |
| `error` | the use case failed | `{"type":"error","content":"<message or traceback>"}` | shows the error under the bubble, stops streaming |
| `complete` | always last | `{"type":"complete","content":""}` | stops the cursor |

Status texts come only from `SsePresenter.STEP_STATUS` and the run_tools rule. act, clarify,
feedback, finish and summarize show nothing new. The previous status stays until the next one
or the final frame.

### 11.4 Sequence

```
UI                         Controller                HandleMessage / graph            Models / MCP
│ POST /v1/stream ───────► │ 200 text/event-stream    │                                │
│                          │ task: handle() ────────► │ understand ──────────────────► │ context
│ ◄─ status Understanding ─┤ ◄──── step_started ──────┤                                │
│                          │                          │ plan ────────────────────────► │ plan
│ ◄─ status Preparing ─────┤ ◄──── step_started ──────┤                                │
│                          │                          │ finish, summarize              │
│ ◄─ token, final ─────────┤ ◄──── finished ──────────┤                                │
│ ◄─ complete ─────────────┤ ◄──── queue closed ──────┤                                │
```

### 11.5 Stop, new session, errors on the UI side

- **Stop** aborts the `fetch`. The server sees the client gone: the generator is cancelled
  (`stream cancelled by the client` warning) and the use-case task is cancelled. Steps already
  done may have saved checkpoints, but `finish` (which writes the exchange to history) may not
  have run. In that case the message is not in the history.
- **New session** aborts any stream, makes a new UUID and clears the bubbles. The backend
  starts a new conversation on the next message.
- **HTTP error** (`503` at capacity, `422` bad body, network failure) → `requestError` banner,
  no bubble content.

---

## 12. Errors, limits and cancellation

| What goes wrong | Where it is caught | User sees |
|---|---|---|
| Body invalid (empty message…) | FastAPI validation | HTTP 422 |
| 200 streams already open | controller semaphore | HTTP 503 "Server is at capacity" |
| Unknown `model_name` | `ModelCatalog.turn_settings` raises → `HandleMessage` generic handler | `error` frame with the traceback, then `complete` |
| LLM server down / overloaded (retryable) | `model_call.invoke` → `AgentUnavailableException` → `HandleMessage` | `error`: "The assistant is temporarily unavailable…" |
| Other model error, bug in a step | `HandleMessage` generic handler (logged `unhandled agent error`) | `error` frame with the traceback |
| Context / review JSON unreadable | `UnderstandStep` / `ReviewStep` | nothing visible; task fallback / accept |
| Tool fails / unknown tool | `Toolbox`, `McpTool` | nothing directly; the act model sees `Error: …` |
| MCP server down at boot | `AgentDI._discover_tools` | the agent runs without those tools |
| MongoDB down at boot | `AgentDI._mongo_connection` | SQLite is used (no TTL) |
| Summary fails | `SummarizeStep` | nothing; history not compacted this time |
| Loop that never ends | policy limits (20 steps, 2 retries), then `recursion_limit` 56 | `budget_exhausted` answer |
| Exception while writing the stream | controller generator | `error` frame with the traceback |
| Client disconnects | controller generator | the use-case task is cancelled |

---

## 13. Things worth knowing

These are facts about the current code and config that surprise when reasoning about
behaviour. None is fixed here.

1. **The model dropdown has no effect on which model answers** while every role in
   `agent.yml` sets `parameters.model`. The selected name must still exist in `llm.yml` or the
   request fails. Set a role's `model: null` to let it follow the selection.
2. **The turn budget comes from `agent_act`**, not from the selected model:
   `max_iterations: 20`, `max_reflection_retries: 2`, `max_context_tokens: 16384`,
   `use_streaming: true`.
3. **The context model still sometimes classes "explain change.md" as direct.** S5/S6 recover
   it at the cost of one extra act call.
4. **"step N" in the logs restarts at 1 when a plan starts executing**, because
   `Turn.execute` clears the work (by design).
5. **No log line names the tool that ran.** The only trace is `MCP session established`, one
   per tool call, since each call opens its own session. Failures are logged.
6. **Readiness follows the boot.** The lifespan sets `app.state.ready` from
   `container.is_ready` once the routers are included, and back to `False` on shutdown, so
   `/actuator/health/readiness` answers 503 while booting or stopping and 200 in between
   (fixed 2026-10-02; it used to answer 503 forever).
7. **Every failure reaches the UI as an `error` event.** A crash while writing the stream
   used to go out as an `event: final` frame with an `error` field the UI ignored; since
   2026-10-02 `SsePresenter.error` sends a proper `error` frame, like use-case failures. The
   UI keeps the traceback's line breaks under the bubble.
8. **The dev proxy targets port 8001** while `make run` and Docker use 8000. In homelab-infra,
   8001 is agent-toolbox.
9. **A direct question answered after an auto-approved plan without tools skips review**
   (S6 edge case), because the intent stays `direct`.
10. **`stream_answer` is not real streaming**: the whole answer arrives in one `token` frame
    just before `final`.

---

## 14. Tests

`make check` = ruff + ty + pytest (230 tests on 2026-10-02). `make evaluation` runs the
model-quality suite separately.

| Path | What it covers |
|---|---|
| `tests/architecture/test_boundaries.py` | Import rules: domain free of frameworks and outer layers; application imports only the domain; nothing in the hexagon imports `bootstrap`; outbound never imports inbound; no direct toolbox package import; LangGraph nodes only delegate to the application |
| `tests/agent_orchestrator/domain/builders.py` | Test helpers: `turn()`, `answer`, `calling`, `result`, `retry`, `accept`, `PLAN` |
| `tests/agent_orchestrator/domain/conversation/test_conversation.py` | interpret (approve, keep, drop), submit (wait / auto-approve), close, compact |
| `tests/agent_orchestrator/domain/turn/test_turn.py`, `test_understanding.py` | Turn changes and questions, conclude, execute clears work; normalisation |
| `tests/agent_orchestrator/domain/workflow/test_transitions.py`, `test_turn_policy.py` | Targets per step, every row of the policy, conditions |
| `tests/agent_orchestrator/application/fakes.py` | Scripted fakes for every port; `InMemoryWorkflowRunner` |
| `tests/agent_orchestrator/application/test_steps.py` | Each step handler |
| `tests/agent_orchestrator/application/test_handle_message.py` | Turn creation, event publishing, error handling, auto-approve pass-through |
| `tests/agent_orchestrator/scenarios/test_turn_scenarios.py` | Whole turns on **both** runners (in-memory and LangGraph with `InMemorySaver`): task → approval → tools, follow-up, retry, clarification, budget, old-format state, misread direct, auto-approve |
| `tests/agent_orchestrator/adapter/outbound/langgraph/test_agent_graph.py` | Compiled edges equal the policy; node/handler pairing |
| `tests/agent_orchestrator/adapter/outbound/llm/…` | Prompts, role adapters (with fake chat models), model plumbing, chat factory, mapper |
| `tests/agent_orchestrator/adapter/outbound/test_*` and `tool/mcp/…` | Toolbox, registry, MCP tool and session factory (against `tests/support/mcp_test_server.py`), event queue |
| `tests/agent_orchestrator/adapter/inbound/web/…` | Controller (admission, cancellation), presenter, schemas |
| `tests/bootstrap/…` | App factory, configuration, settings, container, DI, routers |
| `tests/evaluation/…` | DeepEval-style quality tests (relevancy, faithfulness, hallucination, tool correctness, bias, toxicity) with a local judge model; marked `evaluation`, excluded from `make test` |
| `tests/conftest.py` | Shared fixtures: a recording `logger` (`logger.messages("warning")`) |

UI tests: `npx ng test --watch=false` in homelab-ui (`agent.store.spec.ts`: statuses, final
content, auto-approve sent).

---

## 15. Reasoning cheat sheet

**"Why did it take that path?"** Read the `Understood:` debug line for the intent, then walk
the table in 7.1 from the step it was in. The first row whose condition holds is the answer.

**"Why did it plan instead of answer?"** Either the intent was task / plan_revision (row 1),
or the act model wrote `NEEDS_PLAN:` (row 7).

**"Why did it answer without a review?"** Intent `direct` and no tool used (row 10), or the
answer was set by clarify / plan, or the budget ran out (row 8).

**"Why does it not remember X?"** History is only user messages and final answers, trimmed
to `context_tokens` (most recent first), plus the summary. Tool outputs of earlier turns are
gone unless the answer quoted them. A new `request_id` or an expired checkpoint means an
empty conversation.

**"Where do I change…"**

| To change | Edit |
|---|---|
| when a step follows another | `domain/workflow/turn_policy.py` (+ a condition in `conditions.py`); the graph follows by itself |
| what a step does | its handler in `application/step/` |
| what a model is told | `adapter/outbound/llm/langchain/prompts/` |
| which model a role uses | `config/<env>/operation/agent.yml` |
| the turn budget | `agent_act` parameters in `agent.yml` |
| what the UI sees for a step | `adapter/inbound/web/sse_presenter.py` (`STEP_STATUS`) |
| a LangGraph-only feature for one step | override `work` in that step's `node/*_node.py` |
| a new request option | `AgentRequestSchema` → `AgentRequest` → `TurnOptions` → read it in the domain |

**Log lines and the step they belong to**

| Log | Step |
|---|---|
| `stream request accepted` | controller (stage 3) |
| `Calling the context model` / `Understood: …` | understand |
| `Calling the plan model` | plan |
| `Calling the act model (step N)` | act (N = drafts so far + 1) |
| `MCP session established …` | run_tools (one per tool call) |
| `Calling the reflection model` | review |
| `Retry N with critique: …` | feedback |
| `Calling the summary model` | summarize (only when compacting) |
| `stream cancelled by the client` | the UI stopped or left |
