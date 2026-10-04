# How a message travels through the agent

This guide follows one user message from the UI to the answer. It covers:

- the **routing**: which steps run, in what order, and why;
- the **delivery**: how the answer comes back, piece by piece (`stream`) or all at once (`whole`).

Then scenarios show, step by step, what happens inside the agent for typical messages.

The sources of truth are in the code, and this guide describes them as they are today:

- **routing**: `domain/workflow/turn_policy.py` (`TurnPolicy.TRANSITIONS`) and the conditions in `domain/workflow/conditions.py`;
- **what a step does**: `application/step/*_step.py`;
- **delivery**: `AGENT_ANSWER_DELIVERY`, read in `bootstrap/configuration/settings.py` and wired in `AgentDI._final_reply`;
- **events to SSE**: `adapter/inbound/web/sse_presenter.py`.

New steps, intents or events can be added later. The mechanics below stay the same: a step changes the turn, and the policy picks the next step from the turn.

---

## 1. The big picture

```text
  UI                                    agent-orchestrator
  ──                                    ──────────────────
  POST /v1/stream ─────────────────────► StreamAgentController
  { message, model_name,                    │ starts HandleMessage as a task
    request_id, auto_approve }              ▼
                                         HandleMessage
                                            │ Turn(request, model, budget of the model)
                                            ▼
                                         LangGraphWorkflowRunner
                                            │ loads the conversation (request_id = thread)
                                            ▼
                         ┌──────────── the graph: one node per step ────────────┐
                         │  understand ─► plan / clarify / act ─► … ─► finish   │
                         │  each node: publish "step started" ─► run the step   │
                         │  the policy picks the next node from the turn        │
                         └──────────────────────────┬───────────────────────────┘
                                                    │ TurnEvents
                                                    ▼
  ◄──────────── SSE frames ──────────────────── SsePresenter
  status · token · final · error · complete
```

- **Conversation** is what is remembered between messages: the messages, a summary of older
  ones, and a plan waiting for approval. It is saved in the checkpointer under the
  `request_id`.
- **Turn** is everything about one message: the request, the model, the budget, what was
  understood, the plan being carried out, the work log (drafts, tool results, critiques),
  the review verdicts and the answer.
- **TurnEvent** is what the turn tells the outside while it runs:
  - `step_started`;
  - `answer_delta` (a piece of the answer);
  - `finished`;
  - `failed`.

---

## 2. The steps

| Step | What it does | Model role |
|---|---|---|
| understand | Classifies the message into an intent, rewrites it as a standalone query, and writes 1 to 3 success criteria | `agent_context` |
| plan | Writes a plan with the tools, or revises the pending one. Without auto-approve it stops and asks for approval; with it, the plan starts at once | `agent_plan` |
| clarify | Answers with the clarification question the understand step wrote | none |
| act | Writes a draft. Under a plan it may call tools. Outside a plan it may only ask for a plan (`request_plan` tool) | `agent_act` |
| run_tools | Runs every tool call of the last draft, in parallel, and records the results | none |
| review | Judges the last draft against the request, the criteria and the tool evidence | `agent_reflection` |
| feedback | Records the reviewer's critique so the next act fixes it | none |
| finish | Turns the last draft into the answer (unless a step already set one) and adds the exchange to the conversation | none |
| summarize | When the history grows past half the context budget, folds the older messages into the summary and keeps the last 4 | `agent_summary` |

The `act` and `review` roles follow the model picked in the UI (`model: null` in
`agent.yml`). The other roles are pinned to a model there. The UI shows them under
"Fixed by the server".

### The intents

| Intent | Meaning | Where it goes next |
|---|---|---|
| `plan_approval` | A plan is pending and the user accepts it | act, carrying out that plan |
| `plan_revision` | A plan is pending and the user wants it changed | plan (revises it) |
| `task` | Needs the user's own data, files or systems, or running code | plan |
| `continuation` | Rework the previous answer: shorter, another format, more detail… | act, then review |
| `direct` | Answerable from the conversation or general knowledge | act, then finish (no review) |
| `ambiguous` | Can't tell what the user wants, even with the conversation | clarify |

Two safety rules apply before routing (`Understanding.normalized`):

- `plan_approval` with no pending plan becomes `direct`;
- `ambiguous` with no question becomes `task`.

If the context model's reply can't be read, the message is treated as a `task`.

---

## 3. The routing table

After each step, `TurnPolicy` reads the rows of that step from top to bottom and takes the
first one whose condition holds.

| # | After | Condition | Next |
|---|---|---|---|
| 1 | understand | the intent needs a plan (`task`, `plan_revision`, or no intent) | plan |
| 2 | understand | the intent is `ambiguous` | clarify |
| 3 | understand | otherwise | act |
| 4 | plan | the turn has a plan to carry out (approved, or auto-approved) | act |
| 5 | plan | otherwise (the plan waits for the user's yes) | finish |
| 6 | clarify | always | finish |
| 7 | act | the draft asks for a plan and the turn has none | plan |
| 8 | act | the draft calls tools but the step budget is spent | finish |
| 9 | act | the draft calls tools | run_tools |
| 10 | act | plain direct answer: intent `direct` and no tool has run | finish |
| 11 | act | otherwise | review |
| 12 | run_tools | always | act |
| 13 | review | rejected, and retries and steps are left | feedback |
| 14 | review | otherwise | finish |
| 15 | feedback | always | act |
| 16 | finish | always | summarize |
| 17 | summarize | always | end |

```text
  understand ──(1)──► plan ──(5) waits for yes ──────────────────┐
   │  │                │ ▲                                       │
   │  │             (4)│ │(7) asks for a plan                    │
   │  │                ▼ │                                       │
   │  └──(3)─────────► act ──(10) plain direct answer ──────────►┤
   │                   │ │                                       │
   │              (9)  │ │ (11)                                  │
   │                   │ ▼                                       │
   │        run_tools ◄┘ review ──(14) accepted ────────────────►┤
   │      (12) back to act │                                     │
   │                       │ (13) rejected                       │
   │                       ▼                                     │
   │                    feedback ──(15) back to act              │
   │                                                             │
   └──(2)──► clarify ──(6)──────────────────────────────────────►┤
                                                                 │
                       summarize ◄──(16)── finish ◄──────────────┘
                           │
                      (17) ▼
                          end
```

Two limits keep a turn bounded:

- **steps**: each draft counts as one step, up to the model's `max_iterations`. When the act
  model still wants tools at the limit, the turn ends with "I reached the step limit…"
  (outcome `budget_exhausted`).
- **retries**: a rejected draft is retried up to `max_reflection_retries` times. After that,
  the last draft is sent anyway (outcome `best_effort`).

---

## 4. How the answer is delivered: `stream` or `whole`

`AGENT_ANSWER_DELIVERY` decides how the act model's reply is read. It's set once, at boot.

| Value | Effect |
|---|---|
| `stream` (default) | An answer that goes straight to the user is sent piece by piece as `token` events while the model writes it, then `final` |
| `whole` | The model's reply is read in one call; only `final` carries the answer |

### Which replies are streamed

Only the reply that becomes the answer without any further check is streamed: the
**plain direct answer** (intent `direct`, no tool run, no plan). The same rule sends the turn
from act straight to finish (row 10).

Every other act call is always read whole, whatever the setting:

- **under a plan**: the reply may call tools, and the answer will be reviewed;
- **a `continuation`**: the answer will be reviewed and may be rejected.

Streaming a draft that the reviewer may reject would show the user an answer, then replace
it with another.

```text
  ActStep ─► LangChainActor.act
                │
                ├─ plan? ── yes ──► WholeReply (tools bound when the plan has tools)
                │
                └─ no ── plain direct answer? ── yes ──► final reply reader
                              │                            ├─ stream: StreamedReply
                              │                            └─ whole:  WholeReply
                              └─ no ──► WholeReply
                  (outside a plan, only the request_plan tool is bound)
```

### What `StreamedReply` does

```text
  model.astream(messages)
      │  for each chunk:
      │    text in the chunk? ──► publish TurnEvent.answer_delta(text)
      │                              └─► LangGraphEventPublisher ─► run's custom stream
      │                                     └─► runner yields it ─► SsePresenter ─► "token"
      │    add the chunk to the reply (text and tool calls)
      ▼
  the whole reply ──► Draft ──► the policy routes it like any other draft
```

- A `request_plan` tool call never shows up as text, so it's never streamed.
- A reasoning model's thinking isn't streamed: the provider sends it apart from the answer
  text, and only the text is published.
- `final` always carries the complete answer. The UI appends the `token` pieces as they
  come, then replaces them with `final`. A client that ignores `token` still gets the full
  answer.

### The SSE frames

| TurnEvent | SSE frame |
|---|---|
| `step_started` (understand / plan / review) | `status`: "Understanding your request" / "Preparing a plan" / "Checking the answer" |
| `step_started` (run_tools) | `status`: "Running file_reader, python_executor" |
| `step_started` (other steps) | nothing |
| `answer_delta` | `token` with the piece |
| `finished` | `final` with the answer and `metadata` {`iteration`, `max_iteration`, `outcome`} |
| `failed` | `error` with what went wrong |
| end of the stream | `complete`, always last |

Every turn also ends with a log line:

- `turn finished: <outcome>, <steps>/<max> steps in <seconds>s`, when the turn completes;
- `turn cancelled after <seconds>s`, when the client left first.

---

## 5. Scenarios

Each scenario shows the steps in order (with the routing row that chose the next one), the
frames the UI receives, and what the user sees. Budgets below assume `max_iterations: 20` and
`max_reflection_retries: 2`.

### S1. A general question, with `stream`

> "What is a KV cache?"

| Step | What happens | Row |
|---|---|---|
| understand | intent `direct`, query "What is a KV cache?" | 3 ► act |
| act | no plan, plain direct answer ► `StreamedReply`: each piece of text is published as it arrives | 10 ► finish |
| finish | the draft becomes the answer (`answered`); the exchange is added to the conversation | 16 |
| summarize | the history is still short: nothing to do | 17 ► end |

```text
  status  "Understanding your request"
  token   "A "
  token   "KV cache "
  token   "keeps the attention keys…"        … many more pieces …
  final   { content: <the whole answer>, metadata: { iteration: 1, max_iteration: 20, outcome: answered } }
  complete
```

The user sees the answer being written a few words at a time, then the complete answer.

### S2. The same question, with `whole`

Same steps and same routing. The act model is called once and nothing is published while it
writes.

```text
  status  "Understanding your request"
  final   { content: <the whole answer>, … outcome: answered }
  complete
```

The user sees "Understanding your request", a pause while the model writes, then the whole
answer at once.

### S3. Reworking the previous answer

> (after S1) "Resume it using bullet points"

| Step | What happens | Row |
|---|---|---|
| understand | intent `continuation` | 3 ► act |
| act | no plan, but not a plain direct answer ► read whole (step 1) | 11 ► review |
| review | no tool ran: general knowledge is allowed; accepts | 14 ► finish |
| finish ► summarize | answer `answered` | 16, 17 |

```text
  status  "Understanding your request"
  status  "Checking the answer"
  final   { … iteration: 1, outcome: answered }
  complete
```

If the reviewer rejects the draft:

```text
  review (rejects) ─13─► feedback (critique added) ─15─► act (step 2, sees the critique)
                   ─11─► review … at most 2 retries ─14─► finish
```

After the last retry the draft is sent anyway, with outcome `best_effort`. No `token` frames
are sent in this scenario, whatever the delivery setting: the answer is checked first.

### S4. A question that needs a tool, without auto-approve

> "What's in change.md?" (classified `direct` by mistake, or the act model realizes it needs a file)

| Step | What happens | Row |
|---|---|---|
| understand | intent `direct` | 3 ► act |
| act | outside a plan only `request_plan` is bound; the model calls `request_plan(reason="read change.md")` ► draft "asks for a plan". Read with the final reply reader, but a tool call has no text, so nothing is streamed | 7 ► plan |
| plan | the planner writes the steps; no auto-approve ► the plan is kept as pending and the answer is the approval request (`awaiting_approval`) | 5 ► finish |
| finish ► summarize | | 16, 17 |

A message classified `task` from the start ("Summarise sales.csv by region") skips act and
goes understand ─1─► plan.

```text
  status  "Understanding your request"
  status  "Preparing a plan"
  final   { content: "<the steps>\n\n---\nReply **yes** to run this plan, or tell me what to change.",
            outcome: awaiting_approval }
  complete
```

The user sees the plan and the "Reply yes" line.

### S5. Approving the plan

> (after S4) "yes"

| Step | What happens | Row |
|---|---|---|
| understand | intent `plan_approval` and a plan is pending ► the turn carries out that plan (its query becomes the plan's task); the pending plan is cleared | 3 ► act |
| act | under a plan: the real tools are bound, read whole; the draft calls `file_reader` (step 1) | 9 ► run_tools |
| run_tools | runs the call, records the result as evidence | 12 ► act |
| act | writes the answer from the evidence (step 2) | 11 ► review |
| review | checks the answer against the evidence; accepts | 14 ► finish |
| finish ► summarize | answer `answered` | 16, 17 |

```text
  status  "Understanding your request"
  status  "Running file_reader"
  status  "Checking the answer"
  final   { … iteration: 2, outcome: answered }
  complete
```

The answer is never streamed here: it comes from tools and is reviewed first.

### S6. A task with auto-approve on

> "Summarise sales.csv by region", with **Auto-approve plans** on

| Step | What happens | Row |
|---|---|---|
| understand | intent `task` | 1 ► plan |
| plan | auto-approve ► the plan starts at once instead of waiting | 4 ► act |
| act ⇄ run_tools | as in S5, as many rounds as the plan needs (each draft is one step) | 9, 12 |
| act | final draft without tool calls | 11 ► review |
| review ► finish ► summarize | | 14, 16, 17 |

```text
  status  "Understanding your request"
  status  "Preparing a plan"
  status  "Running file_reader"
  status  "Running python_executor"
  status  "Running file_writer"
  status  "Checking the answer"
  final   { … iteration: 4, outcome: answered }
  complete
```

### S7. Changing the plan instead of approving it

> (after S4) "Also count the lines"

| Step | What happens | Row |
|---|---|---|
| understand | intent `plan_revision`: the pending plan is kept | 1 ► plan |
| plan | the planner revises the pending plan ► a new approval request | 5 ► finish |

The user gets the revised plan and answers **yes** (S5) or asks for more changes (S7 again).

### S8. A message that can't be understood

> "Do the same for the other one" (with nothing in the conversation to resolve it)

| Step | What happens | Row |
|---|---|---|
| understand | intent `ambiguous` with a question ("Which file do you mean?") | 2 ► clarify |
| clarify | the question is the answer (`clarification`) | 6 ► finish |

If the context model marks the message `ambiguous` without writing a question, it becomes a
`task` and goes to plan (row 1) instead.

### S9. Running out of steps

Under a plan, the act model keeps calling tools. At step 20 (the model's `max_iterations`),
its draft still calls tools:

```text
  act (step 20, calls tools) ─8─► finish
      answer: "I reached the step limit before finishing this task. Ask me to continue,
               or narrow the request."   (outcome budget_exhausted)
```

The LangGraph recursion limit is set above this budget
(`10 + 2 × max_steps + 3 × max_retries`), so the policy's limit is always the one reached.

### S10. Something goes wrong

| What | What the user gets | Log |
|---|---|---|
| The model provider keeps failing (retryable error) | `error`: "The assistant is temporarily unavailable…", then `complete` | `agent unavailable: …` |
| Any other error inside the turn | `error` with the trace, then `complete` | `unhandled agent error: …` |
| Unknown `model_name` | `error`, then `complete`; no step runs | `unhandled agent error: … Unknown model '<name>'` |
| The user leaves (closes the tab, or the request is stopped) | nothing more; the turn is cancelled and its model calls stop | `stream cancelled by the client`, `turn cancelled after …s` |

A cancelled turn never reaches finish, so its exchange isn't added to the conversation.

---

## 6. Where the conversation changes

| Moment | Change |
|---|---|
| understand, `plan_approval` with a pending plan | the pending plan moves into the turn and is cleared |
| understand, any other intent | the pending plan is dropped, except for `plan_revision` and `ambiguous` |
| plan without auto-approve | the plan becomes the pending plan |
| finish | the user's message and the answer are appended |
| summarize | the older messages become the summary; the last 4 are kept |

The next message is understood with this conversation: its history (and summary) is how a
short follow-up like "make it shorter" or "yes" makes sense.
