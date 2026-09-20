# Changed files across projects

Generated via `git status --porcelain` in each project on 2026-09-18.
Lists only files with uncommitted changes (modified / untracked / deleted).
`pycraftcore` is clean (everything committed and pushed) — nothing to list there.

## agent-toolbox

| File | Relative path |
|---|---|
| .env.example | .env.example |
| cicd.yml | .github/workflows/cicd.yml |
| .gitignore | .gitignore |
| Readme.md | Readme.md |
| mcp.yml | config/debug/connector/mcp.yml |
| telemetry.yml | config/debug/connector/telemetry.yml |
| Dockerfile | devops/docker/Dockerfile |
| Chart.yaml *(deleted)* | devops/helm/Chart.yaml |
| deployment.yaml *(deleted)* | devops/helm/templates/deployment.yaml |
| service.yaml *(deleted)* | devops/helm/templates/service.yaml |
| values.yaml *(deleted)* | devops/helm/values.yaml |
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
| cicd.yml | .github/workflows/cicd.yml |
| .gitignore | .gitignore |
| Makefile | Makefile |
| Readme.md | Readme.md |
| api.yml | config/debug/connector/api.yml |
| database.yml | config/debug/connector/database.yml |
| mcp.yml | config/debug/connector/mcp.yml |
| telemetry.yml | config/debug/connector/telemetry.yml |
| llm.yml | config/debug/operation/llm.yml |
| root.yml | config/root.yml |
| Dockerfile | devops/docker/Dockerfile |
| Chart.yaml *(deleted)* | devops/helm/Chart.yaml |
| deployment.yaml *(deleted)* | devops/helm/templates/deployment.yaml |
| service.yaml *(deleted)* | devops/helm/templates/service.yaml |
| values.yaml *(deleted)* | devops/helm/values.yaml |
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
| test_mcp_tool.py | tests/agent_orchestrator/adapter/outbound/test_mcp_tool.py |
| test_streamable_http_session_factory.py | tests/agent_orchestrator/adapter/outbound/tool/mcp/test_streamable_http_session_factory.py |
| test_streamable_http_session_factory_live.py *(deleted)* | tests/agent_orchestrator/adapter/outbound/tool/mcp/test_streamable_http_session_factory_live.py |
| test_agent_application.py | tests/bootstrap/application/test_agent_application.py |
| test_application_configuration.py | tests/bootstrap/configuration/test_application_configuration.py |
| test_agent_container.py | tests/bootstrap/container/test_agent_container.py |
| test_agent_di.py | tests/bootstrap/di/test_agent_di.py |
| test_base_di.py | tests/bootstrap/di/test_base_di.py |
| test_actuator_router.py | tests/bootstrap/router/actuator/test_actuator_router.py |
| conftest.py | tests/conftest.py |
| conftest.py | tests/evaluation/conftest.py |
| uv.lock | uv.lock |
