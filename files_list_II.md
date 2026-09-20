# Changed files across projects

Generated via `git status --porcelain` in each project on 2026-09-18.
Lists only files with uncommitted changes (modified / untracked).

## agent-toolbox

| File | Relative path |
|---|---|
| .env.example | .env.example |
| .gitignore | .gitignore |
| Readme.md | Readme.md |
| mcp.yml | config/debug/connector/mcp.yml |
| telemetry.yml | config/debug/connector/telemetry.yml |
| values.yaml | devops/helm/values.yaml |
| pyproject.toml | pyproject.toml |
| mcp_asgi_factory.py | src/agent_toolbox/adapter/inbound/mcp/mcp_asgi_factory.py |
| tool_binder.py | src/agent_toolbox/adapter/inbound/mcp/tool_binder.py |
| tool_bridge.py | src/agent_toolbox/adapter/outbound/code/tool_bridge.py |
| reader_tool.py | src/agent_toolbox/adapter/outbound/file/reader_tool.py |
| writer_tool.py | src/agent_toolbox/adapter/outbound/file/writer_tool.py |
| file_reader.py | src/agent_toolbox/adapter/outbound/specification/file_reader.py |
| file_writer.py | src/agent_toolbox/adapter/outbound/specification/file_writer.py |
| python_sandbox.py | src/agent_toolbox/adapter/outbound/specification/python_sandbox.py |
| user_database.py | src/agent_toolbox/adapter/outbound/specification/user_database.py |
| sql_tool.py | src/agent_toolbox/adapter/outbound/sql/sql_tool.py |
| tool_specification.py | src/agent_toolbox/domain/model/tool_specification.py |
| application_configuration.py | src/bootstrap/configuration/application_configuration.py |
| toolbox_container.py | src/bootstrap/container/toolbox_container.py |
| base_di.py | src/bootstrap/di/base_di.py |
| toolbox_di.py | src/bootstrap/di/toolbox_di.py |
| test_actuator.py | tests/agent_toolbox/adapter/inbound/mcp/test_actuator.py |
| test_specifications.py | tests/agent_toolbox/adapter/outbound/specification/test_specifications.py |
| test_tools.py | tests/agent_toolbox/adapter/outbound/test_tools.py |
| test_toolbox_application.py | tests/bootstrap/application/test_toolbox_application.py |
| test_toolbox_container.py | tests/bootstrap/container/test_toolbox_container.py |
| test_toolbox_di.py | tests/bootstrap/di/test_toolbox_di.py |
| uv.lock | uv.lock |

## agent-orchestrator

| File | Relative path |
|---|---|
| .env.example | .env.example |
| .gitignore | .gitignore |
| Readme.md | Readme.md |
| api.yml | config/debug/connector/api.yml |
| database.yml | config/debug/connector/database.yml |
| mcp.yml | config/debug/connector/mcp.yml |
| telemetry.yml | config/debug/connector/telemetry.yml |
| llm.yml | config/debug/operation/llm.yml |
| root.yml | config/root.yml |
| values.yaml | devops/helm/values.yaml |
| pyproject.toml | pyproject.toml |
| __init__.py | src/__init__.py |
| stream_agent_controller.py | src/agent_orchestrator/adapter/inbound/web/controller/stream_agent_controller.py |
| prompt_service.py | src/agent_orchestrator/adapter/outbound/langgraph/service/prompt_service.py |
| mcp_session_factory.py | src/agent_orchestrator/adapter/outbound/tool/mcp/mcp_session_factory.py |
| mcp_tool.py | src/agent_orchestrator/adapter/outbound/tool/mcp/mcp_tool.py |
| mcp_tool_provider.py | src/agent_orchestrator/adapter/outbound/tool/mcp/mcp_tool_provider.py |
| streamable_http_session_factory.py | src/agent_orchestrator/adapter/outbound/tool/mcp/streamable_http_session_factory.py |
| agent_application.py | src/bootstrap/application/agent_application.py |
| agent_container.py | src/bootstrap/container/agent_container.py |
| agent_di.py | src/bootstrap/di/agent_di.py |
| base_di.py | src/bootstrap/di/base_di.py |
| actuator_router.py | src/bootstrap/router/actuator/actuator_router.py |
| response.py | src/bootstrap/router/actuator/schema/response.py |
| test_agent_application.py | tests/bootstrap/application/test_agent_application.py |
| test_application_configuration.py | tests/bootstrap/configuration/test_application_configuration.py |
| test_agent_container.py | tests/bootstrap/container/test_agent_container.py |
| test_agent_di.py | tests/bootstrap/di/test_agent_di.py |
| test_base_di.py | tests/bootstrap/di/test_base_di.py |
| test_actuator_router.py | tests/bootstrap/router/actuator/test_actuator_router.py |
| conftest.py | tests/conftest.py |
| conftest.py | tests/evaluation/conftest.py |
| uv.lock | uv.lock |

## pycraftcore

| File | Relative path |
|---|---|
| telemetry.yml | config/debug/connector/telemetry.yml |
| pyproject.toml | pyproject.toml |
| __init__.py | src/pycraftcore/logger/adapter/__init__.py |
| loguru_logger.py | src/pycraftcore/logger/adapter/loguru_logger.py |
| standard_logger.py *(new)* | src/pycraftcore/logger/adapter/standard_logger.py |
| __init__.py | src/pycraftcore/logger/port/__init__.py |
| log_sink.py *(new)* | src/pycraftcore/logger/port/log_sink.py |
| __init__.py | src/pycraftcore/telemetry/adapter/__init__.py |
| open_telemetry.py | src/pycraftcore/telemetry/adapter/open_telemetry.py |
| open_telemetry_logger_provider.py *(new)* | src/pycraftcore/telemetry/adapter/open_telemetry_logger_provider.py |
| open_telemetry_meter_provider.py *(new)* | src/pycraftcore/telemetry/adapter/open_telemetry_meter_provider.py |
| open_telemetry_provider.py *(new)* | src/pycraftcore/telemetry/adapter/open_telemetry_provider.py |
| open_telemetry_tracer.py *(new)* | src/pycraftcore/telemetry/adapter/open_telemetry_tracer.py |
| __init__.py | src/pycraftcore/telemetry/port/__init__.py |
| telemetry.py | src/pycraftcore/telemetry/port/telemetry.py |
| logger_provider.py *(new)* | src/pycraftcore/telemetry/port/logger_provider.py |
| meter_provider.py *(new)* | src/pycraftcore/telemetry/port/meter_provider.py |
| trace_provider.py *(new)* | src/pycraftcore/telemetry/port/trace_provider.py |
| tracer.py *(new)* | src/pycraftcore/telemetry/port/tracer.py |
| test_omega_configuration_reader.py | tests/application_configuration/test_omega_configuration_reader.py |
| test_logger.py | tests/ducktype/test_logger.py |
| test_loguru_logger.py | tests/logger/adapter/test_loguru_logger.py |
| test_standard_logger.py *(new)* | tests/logger/adapter/test_standard_logger.py |
| test_open_telemetry.py | tests/telemetry/adapter/test_open_telemetry.py |
| test_open_telemetry_logger_provider.py *(new)* | tests/telemetry/adapter/test_open_telemetry_logger_provider.py |
| test_open_telemetry_meter_provider.py *(new)* | tests/telemetry/adapter/test_open_telemetry_meter_provider.py |
| test_open_telemetry_provider.py *(new)* | tests/telemetry/adapter/test_open_telemetry_provider.py |
| test_open_telemetry_tracer.py *(new)* | tests/telemetry/adapter/test_open_telemetry_tracer.py |
| uv.lock | uv.lock |

Note: `pycraftcore/.env` (local, gitignored) was also edited -- `OTEL_HOST`/`OTEL_PORT` filled in with real values.
