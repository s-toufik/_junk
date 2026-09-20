# Changed files across projects

Generated via `git status --porcelain` in each project on 2026-09-18.
Lists only files with uncommitted changes (modified / renamed / untracked).

## agent-toolbox

| File | Relative path |
|---|---|
| .env.example | .env.example |
| .gitignore | .gitignore |
| mcp.yml | config/debug/connector/mcp.yml |
| telemetry.yml | config/debug/connector/telemetry.yml |
| values.yaml | devops/helm/values.yaml |
| pyproject.toml | pyproject.toml |
| mcp_asgi_factory.py | src/agent_toolbox/adapter/inbound/mcp/mcp_asgi_factory.py |
| tool_binder.py | src/agent_toolbox/adapter/inbound/mcp/tool_binder.py |
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
| .gitignore | .gitignore |
| pyproject.toml | pyproject.toml |
| connector.py | src/pycraftcore/application_configuration/model/connector.py |
| factory.py | src/pycraftcore/file_handler/adapter/factory.py |
| __init__.py | src/pycraftcore/file_handler/schema/__init__.py |
| factory.py | src/pycraftcore/repository/adapter/no_sql/mongodb/factory.py |
| adapter.py | src/pycraftcore/runtime/adapter/python/adapter.py |
| factory.py | src/pycraftcore/runtime/adapter/python/factory.py |
| python_runner_template.py | src/pycraftcore/runtime/adapter/python/python_runner_template.py |
| __init__.py | src/pycraftcore/runtime/schema/__init__.py |
| test_factory.py | tests/file_handler/adapter/test_factory.py |
| test_factory.py | tests/repository/adapter/no_sql/mongodb/test_factory.py |
| test_adapter.py | tests/runtime/adapter/python/test_adapter.py |
| test_factory.py | tests/runtime/adapter/python/test_factory.py |
| __init__.py *(renamed from tests/runtime/configuration/__init__.py)* | tests/runtime/schema/__init__.py |
| test_safe_code_settings.py *(renamed + modified, was tests/runtime/configuration/test_schema.py)* | tests/runtime/schema/test_safe_code_settings.py |
| test_code_stdout.py *(untracked/new)* | tests/runtime/schema/test_code_stdout.py |
| test_host_bridge.py *(untracked/new)* | tests/runtime/schema/test_host_bridge.py |
| uv.lock | uv.lock |
