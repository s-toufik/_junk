# Changed files — freeze

Every uncommitted change, as of 2026-09-26 and updated 2026-09-27, in the repositories
involved in the agent work: including changes that were already in progress before this work
(e.g. the tool-contract refactor in agent-toolbox and pycraftcore, the chat redesign in
homelab-ui), not only the files touched in it. Built from `git status` in each repository
(untracked files included, ignored files excluded).

Entries are cumulative: a file stays listed after it has been committed, and later updates only
add lines.

Update of 2026-09-27: 20 files added by the move from loguru to standard logging
(pycraftcore 2.0.0 `configure_logging`, both apps on `StandardLogger` + `LOG_LEVEL`, homelab
compose `LOGURU_LEVEL` → `LOG_LEVEL`). Before building the app images: publish pycraftcore
2.0.0, remove `[tool.uv.sources]` from both apps and run `uv lock`.

A moved or renamed file appears twice: deleted at its old path, added at its new one.

358 entries across 5 repositories: agent-orchestrator 215, agent-toolbox 89, pycraftcore 35, homelab-infra 4, homelab-ui 15.

Other repositories under `~/SandBox` with uncommitted changes, unrelated to this work and
not listed: `archetype` (`.DS_Store`), `notes` (Obsidian notes and settings),
`projects/c++/pricelabcpp-core` (`.gitignore`, `Makefile`, `.DS_Store`),
`projects/python/pricelab/pricelab-core` and `projects/python/pricelab/pricelab-retriever`
(earlier pricelab work).

## agent-orchestrator (215 files)

Branch `develop`, on top of `38ec195 fix(mcp_tool): correctly handle structured and unstructured MCP tool outputs`. Now on top of `a9710bd chore(pyproject): update pycraftcore dependency to version 1.6.0`.

### Added (134)

- `config/debug/operation/agent.yml`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/__init__.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/anthropic_sdk_agent.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/enum/__init__.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/enum/intent.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/enum/reflection_action.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/enum/turn_mode.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/enum/turn_outcome.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/options_factory.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/port/__init__.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/port/agent_state_store_port.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/port/query_port.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/prompt/__init__.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/prompt/act_prompt.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/prompt/clock.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/prompt/context_prompt.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/prompt/plan_prompt.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/prompt/reflection_prompt.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/prompt/tool_catalog.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/schema/__init__.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/schema/agent_limits.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/schema/mcp_server.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/schema/model_profile.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/schema/model_roles.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/schema/plan.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/schema/reflection_decision.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/schema/sdk_settings.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/schema/tool_access.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/schema/turn_context.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/schema/turn_models.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/schema/turn_state.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/service/__init__.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/service/event_channel.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/service/structured_output.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/step/__init__.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/step/act_step.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/step/agent_steps.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/step/clarify_step.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/step/context_step.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/step/feedback_step.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/step/finalize_step.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/step/ingest_step.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/step/plan_step.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/step/reflect_step.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/step/summarize_step.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/step/tools_step.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/store/__init__.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/store/agent_state.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/store/exchange.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/store/mongo_agent_state_store.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/store/mongo_session_store.py`
- `src/agent_orchestrator/adapter/outbound/anthropic_sdk/turn_controls.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/agent_router.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/enum/intent.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/enum/turn_outcome.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/langgraph_agent.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/node/act_node.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/node/clarify_node.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/node/context_node.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/node/finalize_node.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/node/ingest_node.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/node/plan_node.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/node/reflect_node.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/node/summarize_node.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/node/tools_node.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/port/__init__.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/port/node_port.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/prompt/__init__.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/prompt/act_prompt.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/prompt/clock.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/prompt/context_prompt.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/prompt/plan_prompt.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/prompt/reflection_prompt.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/prompt/summary_prompt.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/prompt/tool_catalog.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/schema/agent_limits.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/schema/plan.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/schema/turn_context.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/schema/turn_state.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/service/context_window.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/service/structured_output.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/store/__init__.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/store/agent_state.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/store/graph_state.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/store/state_serialization.py`
- `src/agent_orchestrator/adapter/outbound/llm/enum/__init__.py`
- `src/agent_orchestrator/adapter/outbound/llm/enum/reasoning_effort.py`
- `src/agent_orchestrator/adapter/outbound/llm/langchain/__init__.py`
- `src/agent_orchestrator/adapter/outbound/llm/langchain/chat_factory.py`
- `src/agent_orchestrator/adapter/outbound/llm/lite_llm/__init__.py`
- `src/agent_orchestrator/adapter/outbound/llm/lite_llm/lite_llm_config.py`
- `src/agent_orchestrator/adapter/outbound/llm/lite_llm/lite_llm_gateway.py`
- `src/agent_orchestrator/adapter/outbound/tool/tool_port.py`
- `src/agent_orchestrator/application/port/outbound/event_stream_port.py`
- `src/bootstrap/configuration/anthropic_sdk_settings.py`
- `src/bootstrap/di/anthropic_sdk_di.py`
- `src/bootstrap/di/langgraph_di.py`
- `tests/agent_orchestrator/adapter/outbound/anthropic_sdk/__init__.py`
- `tests/agent_orchestrator/adapter/outbound/anthropic_sdk/fakes.py`
- `tests/agent_orchestrator/adapter/outbound/anthropic_sdk/step/__init__.py`
- `tests/agent_orchestrator/adapter/outbound/anthropic_sdk/step/test_act_step.py`
- `tests/agent_orchestrator/adapter/outbound/anthropic_sdk/step/test_context_step.py`
- `tests/agent_orchestrator/adapter/outbound/anthropic_sdk/step/test_plan_step.py`
- `tests/agent_orchestrator/adapter/outbound/anthropic_sdk/step/test_reflect_step.py`
- `tests/agent_orchestrator/adapter/outbound/anthropic_sdk/step/test_turn_steps.py`
- `tests/agent_orchestrator/adapter/outbound/anthropic_sdk/store/__init__.py`
- `tests/agent_orchestrator/adapter/outbound/anthropic_sdk/store/fake_collection.py`
- `tests/agent_orchestrator/adapter/outbound/anthropic_sdk/store/test_stores.py`
- `tests/agent_orchestrator/adapter/outbound/anthropic_sdk/test_anthropic_sdk_agent.py`
- `tests/agent_orchestrator/adapter/outbound/anthropic_sdk/test_options_factory.py`
- `tests/agent_orchestrator/adapter/outbound/anthropic_sdk/test_structured_output.py`
- `tests/agent_orchestrator/adapter/outbound/anthropic_sdk/test_turn_controls.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/fakes.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/node/test_act_node.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/node/test_context_node.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/node/test_finalize_node.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/node/test_plan_node.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/node/test_reflect_node.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/node/test_summarize_node.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/node/test_tools_node.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/node/test_turn_nodes.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/service/test_context_window.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/service/test_prompts.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/store/__init__.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/store/test_state_serialization.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/test_agent_router.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/test_langgraph_agent.py`
- `tests/agent_orchestrator/adapter/outbound/llm/langchain/__init__.py`
- `tests/agent_orchestrator/adapter/outbound/llm/langchain/test_chat_factory.py`
- `tests/agent_orchestrator/adapter/outbound/llm/lite_llm/__init__.py`
- `tests/agent_orchestrator/adapter/outbound/llm/lite_llm/fake_litellm.py`
- `tests/agent_orchestrator/adapter/outbound/llm/lite_llm/test_lite_llm.py`
- `tests/bootstrap/configuration/test_anthropic_sdk_settings.py`
- `tests/bootstrap/di/test_anthropic_sdk_di.py`

### Modified (54)

- `.env.example`
- `Makefile`
- `Readme.md`
- `config/debug/connector/api.yml`
- `config/debug/operation/llm.yml`
- `config/root.yml`
- `devops/docker/Dockerfile`
- `pyproject.toml`
- `src/agent_orchestrator/adapter/inbound/web/controller/stream_agent_controller.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/agent_graph.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/build_agent.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/node/feedback_node.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/node/node.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/schema/conversation.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/schema/conversation_message.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/schema/reflection_decision.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/service/tokens_service.py`
- `src/agent_orchestrator/adapter/outbound/llm/mapper.py`
- `src/agent_orchestrator/adapter/outbound/llm/schema.py`
- `src/agent_orchestrator/adapter/outbound/streaming/sse_queue.py`
- `src/agent_orchestrator/adapter/outbound/tool/mcp/mcp_tool_provider.py`
- `src/agent_orchestrator/adapter/outbound/tool/tool_registry.py`
- `src/agent_orchestrator/application/port/inbound/stream_agent_port.py`
- `src/agent_orchestrator/application/port/outbound/agent_port.py`
- `src/agent_orchestrator/application/use_case/stream_agent_usecase.py`
- `src/agent_orchestrator/domain/enum/agent_message_status.py`
- `src/agent_orchestrator/domain/exception/agent_unavailable_exception.py`
- `src/agent_orchestrator/domain/exception/tool_unavailable_exception.py`
- `src/agent_orchestrator/domain/exception/unknown_tool_exception.py`
- `src/agent_orchestrator/domain/model/agent_message_stream.py`
- `src/agent_orchestrator/domain/model/tool_specification.py`
- `src/bootstrap/configuration/settings.py`
- `src/bootstrap/container/agent_container.py`
- `src/bootstrap/di/agent_di.py`
- `src/bootstrap/di/base_di.py`
- `tests/agent_orchestrator/adapter/inbound/web/controller/test_stream_agent_controller.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/schema/test_schemas.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/test_build_agent.py`
- `tests/agent_orchestrator/adapter/outbound/llm/test_mapper.py`
- `tests/agent_orchestrator/adapter/outbound/test_mcp_tool.py`
- `tests/agent_orchestrator/adapter/outbound/test_mcp_tool_invoke.py`
- `tests/agent_orchestrator/application/test_stream_agent_usecase.py`
- `tests/agent_orchestrator/domain/test_domain_models.py`
- `tests/architecture/test_boundaries.py`
- `tests/bootstrap/configuration/test_settings.py`
- `tests/bootstrap/container/test_agent_container.py`
- `tests/bootstrap/di/test_agent_di.py`
- `tests/bootstrap/di/test_base_di.py`
- `tests/conftest.py`
- `tests/evaluation/conftest.py`
- `tests/evaluation/local_judge_model.py`
- `tests/evaluation/support.py`
- `tests/support/mcp_test_server.py`
- `uv.lock`

### Deleted (27)

- `src/agent_orchestrator/adapter/outbound/langgraph/lang_agent.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/node/execution_node.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/node/final_node.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/node/memory_node.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/node/planner_node.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/node/reflection_node.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/node/router_node.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/schema/agent_state.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/schema/graph_state.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/schema/planner_decision.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/service/prompt_service.py`
- `src/agent_orchestrator/adapter/outbound/langgraph/service/state_serialization.py`
- `src/agent_orchestrator/adapter/outbound/llm/factory.py`
- `src/agent_orchestrator/application/port/outbound/sse_queue_port.py`
- `src/agent_orchestrator/application/port/outbound/tool_port.py`
- `src/agent_orchestrator/domain/model/agent_message.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/node/test_execution_node.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/node/test_feedback_node.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/node/test_final_node.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/node/test_memory_node.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/node/test_planner_node.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/node/test_reflection_node.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/node/test_router_node.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/service/test_prompt_service.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/service/test_state_serialization.py`
- `tests/agent_orchestrator/adapter/outbound/langgraph/test_lang_agent.py`
- `tests/agent_orchestrator/adapter/outbound/llm/test_factory.py`

## agent-toolbox (89 files)

Branch `develop`, on top of `4a9a252 fix(python_tool): return only stderr on failure ignoring partial stdout`. Now on top of `ba52df8 test(core): replace vault model with working directory model in tests`.

### Added (40)

- `src/agent_toolbox/adapter/inbound/sandbox/__init__.py`
- `src/agent_toolbox/adapter/inbound/sandbox/tool_bridge.py`
- `src/agent_toolbox/adapter/inbound/tool_text.py`
- `src/agent_toolbox/adapter/outbound/code/model/python_execution_input.py`
- `src/agent_toolbox/adapter/outbound/code/model/python_execution_output.py`
- `src/agent_toolbox/adapter/outbound/file/model/file_read_input.py`
- `src/agent_toolbox/adapter/outbound/file/model/file_read_output.py`
- `src/agent_toolbox/adapter/outbound/file/model/file_write_input.py`
- `src/agent_toolbox/adapter/outbound/file/model/file_write_output.py`
- `src/agent_toolbox/adapter/outbound/sandbox/__init__.py`
- `src/agent_toolbox/adapter/outbound/sandbox/python_sandbox.py`
- `src/agent_toolbox/adapter/outbound/sql/model/sql_query_input.py`
- `src/agent_toolbox/adapter/outbound/sql/model/sql_query_output.py`
- `src/agent_toolbox/application/port/inbound/__init__.py`
- `src/agent_toolbox/application/port/inbound/invoke_tool_port.py`
- `src/agent_toolbox/application/port/outbound/code_sandbox_port.py`
- `src/agent_toolbox/application/use_case/invoke_tool_usecase.py`
- `src/agent_toolbox/domain/exception/tool_failure.py`
- `src/agent_toolbox/domain/exception/unknown_tool_exception.py`
- `src/agent_toolbox/domain/model/sandbox_run.py`
- `src/agent_toolbox/domain/model/working_directory.py`
- `tests/agent_toolbox/adapter/inbound/mcp/test_tool_binder.py`
- `tests/agent_toolbox/adapter/inbound/sandbox/__init__.py`
- `tests/agent_toolbox/adapter/inbound/sandbox/test_tool_bridge.py`
- `tests/agent_toolbox/adapter/inbound/test_tool_text.py`
- `tests/agent_toolbox/adapter/outbound/code/__init__.py`
- `tests/agent_toolbox/adapter/outbound/code/test_python_tool.py`
- `tests/agent_toolbox/adapter/outbound/file/__init__.py`
- `tests/agent_toolbox/adapter/outbound/file/test_reader_tool.py`
- `tests/agent_toolbox/adapter/outbound/file/test_writer_tool.py`
- `tests/agent_toolbox/adapter/outbound/sandbox/__init__.py`
- `tests/agent_toolbox/adapter/outbound/sandbox/test_python_sandbox.py`
- `tests/agent_toolbox/adapter/outbound/sql/__init__.py`
- `tests/agent_toolbox/adapter/outbound/sql/test_sql_tool.py`
- `tests/agent_toolbox/application/use_case/__init__.py`
- `tests/agent_toolbox/application/use_case/test_invoke_tool_usecase.py`
- `tests/agent_toolbox/domain/test_working_directory.py`
- `tests/agent_toolbox/stubs.py`
- `tests/contract/__init__.py`
- `tests/contract/test_tool_parity.py`

### Modified (20)

- `.env.example`
- `.gitignore`
- `Readme.md`
- `devops/docker/Dockerfile`
- `pyproject.toml`
- `src/agent_toolbox/adapter/inbound/mcp/tool_binder.py`
- `src/agent_toolbox/adapter/outbound/code/python_tool.py`
- `src/agent_toolbox/adapter/outbound/file/reader_tool.py`
- `src/agent_toolbox/adapter/outbound/file/writer_tool.py`
- `src/agent_toolbox/adapter/outbound/sql/sql_tool.py`
- `src/agent_toolbox/application/port/outbound/tool_port.py`
- `src/bootstrap/configuration/settings.py`
- `src/bootstrap/container/toolbox_container.py`
- `src/bootstrap/di/base_di.py`
- `src/bootstrap/di/toolbox_di.py`
- `tests/architecture/test_boundaries.py`
- `tests/bootstrap/di/test_base_di.py`
- `tests/bootstrap/di/test_toolbox_di.py`
- `tests/conftest.py`
- `uv.lock`

### Deleted (29)

- `src/agent_toolbox/adapter/outbound/code/model/python_execution_result.py`
- `src/agent_toolbox/adapter/outbound/code/tool_bridge.py`
- `src/agent_toolbox/adapter/outbound/file/model/file_read_result.py`
- `src/agent_toolbox/adapter/outbound/file/model/file_write_result.py`
- `src/agent_toolbox/adapter/outbound/registry/__init__.py`
- `src/agent_toolbox/adapter/outbound/registry/in_memory_tool_registry.py`
- `src/agent_toolbox/adapter/outbound/specification/__init__.py`
- `src/agent_toolbox/adapter/outbound/specification/file_reader.py`
- `src/agent_toolbox/adapter/outbound/specification/file_writer.py`
- `src/agent_toolbox/adapter/outbound/specification/python_sandbox.py`
- `src/agent_toolbox/adapter/outbound/specification/user_database.py`
- `src/agent_toolbox/adapter/outbound/sql/model/sql_query_result.py`
- `src/agent_toolbox/application/use_case/execute_tool_usecase.py`
- `src/agent_toolbox/domain/enum/__init__.py`
- `src/agent_toolbox/domain/enum/parameter_type.py`
- `src/agent_toolbox/domain/exception/tool_execution_exeception.py`
- `src/agent_toolbox/domain/exception/unknown_tool_exeception.py`
- `src/agent_toolbox/domain/model/tool_invocation.py`
- `src/agent_toolbox/domain/model/tool_outcome.py`
- `src/agent_toolbox/domain/model/tool_specification.py`
- `tests/agent_toolbox/adapter/inbound/test_tool_binder.py`
- `tests/agent_toolbox/adapter/outbound/specification/__init__.py`
- `tests/agent_toolbox/adapter/outbound/specification/test_specifications.py`
- `tests/agent_toolbox/adapter/outbound/test_in_memory_tool_registry.py`
- `tests/agent_toolbox/adapter/outbound/test_tools.py`
- `tests/agent_toolbox/application/test_execute_tool_usecase.py`
- `tests/agent_toolbox/domain/model/__init__.py`
- `tests/agent_toolbox/domain/model/test_tool_outcome.py`
- `tests/agent_toolbox/domain/test_exceptions.py`

## pycraftcore (35 files)

Branch `develop`, on top of `6f02723 chore(python): improve python runtime environment and extend safe builtins`. Now on top of `0fab0e3 chore(project): bump version to 1.6.0`.

### Added (8)

- `src/pycraftcore/context/__init__.py`
- `src/pycraftcore/context/request_id_context.py`
- `src/pycraftcore/logger/configuration.py`
- `src/pycraftcore/runtime/adapter/python/host_bridge_server.py`
- `src/pycraftcore/runtime/schema/code_result.py`
- `tests/logger/test_configuration.py`
- `tests/runtime/adapter/python/test_host_bridge_server.py`
- `tests/runtime/schema/test_code_result.py`

### Modified (24)

- `Readme.md`
- `pyproject.toml`
- `src/pycraftcore/file_handler/adapter/extension/markdown/markdown_writer.py`
- `src/pycraftcore/http/context/request_context.py`
- `src/pycraftcore/logger/__init__.py`
- `src/pycraftcore/logger/adapter/__init__.py`
- `src/pycraftcore/logger/adapter/standard_logger.py`
- `src/pycraftcore/logger/port/__init__.py`
- `src/pycraftcore/runtime/adapter/__init__.py`
- `src/pycraftcore/runtime/adapter/python/__init__.py`
- `src/pycraftcore/runtime/adapter/python/adapter.py`
- `src/pycraftcore/runtime/adapter/python/factory.py`
- `src/pycraftcore/runtime/adapter/python/python_runner_template.py`
- `src/pycraftcore/runtime/schema/__init__.py`
- `src/pycraftcore/runtime/schema/host_bridge.py`
- `src/pycraftcore/runtime/schema/safe_code_settings.py`
- `src/pycraftcore/telemetry/adapter/open_telemetry_logger_provider.py`
- `src/pycraftcore/telemetry/adapter/open_telemetry_provider.py`
- `src/pycraftcore/telemetry/adapter/open_telemetry_tracer.py`
- `tests/ducktype/test_logger.py`
- `tests/file_handler/adapter/extension/test_markdown_writer.py`
- `tests/runtime/schema/test_safe_code_settings.py`
- `tests/telemetry/adapter/test_open_telemetry_logger_provider.py`
- `uv.lock`

### Deleted (3)

- `src/pycraftcore/logger/adapter/loguru_logger.py`
- `src/pycraftcore/logger/port/log_sink.py`
- `tests/logger/adapter/test_loguru_logger.py`

## homelab-infra (4 files)

Branch `develop`, on top of `b47337c chore(agent-orchestrator): add LOGURU_LEVEL env variable to compose config`. Now on top of `2fa23fe docs(agent): add shared working directory usage information`.

### Modified (4)

- `.env.example`
- `README.md`
- `agent-orchestrator/compose.yml`
- `agent-toolbox/compose.yml`

## homelab-ui (15 files)

Branch `develop`, on top of `d27c3cf fix(agent): remove deprecated model 'qwen3-32b' from known models list`. Now on top of `2a87d7a fix(agent): add resend event handling to conversation component`.

### Added (1)

- `src/app/features/agent/application/agent.store.spec.ts`

### Modified (14)

- `proxy.conf.json`
- `src/app/features/agent/application/agent.store.ts`
- `src/app/features/agent/components/composer/composer.html`
- `src/app/features/agent/components/composer/composer.scss`
- `src/app/features/agent/components/conversation/conversation.html`
- `src/app/features/agent/components/conversation/conversation.ts`
- `src/app/features/agent/components/message/message.html`
- `src/app/features/agent/components/message/message.scss`
- `src/app/features/agent/components/message/message.ts`
- `src/app/features/agent/domain/chat-message.ts`
- `src/app/features/agent/domain/stream-event.ts`
- `src/app/features/agent/pages/agent-page/agent-page.html`
- `src/app/features/agent/pages/agent-page/agent-page.ts`
- `src/styles.scss`

## Not tracked by git

`agent-orchestrator/sandbox/` is ignored by git, so it is not in the lists above. Written
during this work:

- `sandbox/readme_interne.md` (updated)
- `sandbox/readme_interne_anthropic_sdk.md` (new)
- `sandbox/readme_interne_engines_comparison.md` (new)
- `sandbox/changed_freeze.md` (this file)
