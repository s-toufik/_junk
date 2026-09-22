# Files touched this session

Every file created or edited by Claude across the three projects during this session
(typed MCP tool outputs: `ToolOutcome`/`ToolSpecification` generics, per-tool output
models, `structured_output=True`, the pycraftcore host-bridge fix, agent-orchestrator
consuming `structuredContent`, and the orjson conversion of `JSONSerializer`).

## pycraftcore

| File | Path | What changed |
|---|---|---|
| python_runner_template.py | `src/pycraftcore/runtime/adapter/python/python_runner_template.py` | Host bridge no longer double-decodes JSON; `_HostBridge.call` returns the native value instead of a string needing a second `json.loads` |
| pyproject.toml | `pyproject.toml` | Version bump `1.2.0` → `1.3.0` (breaking change to the host-bridge wire contract) |
| json_serializer.py | `src/pycraftcore/serializer/adapter/json_serializer.py` | Switched from stdlib `json.dumps(asdict(...))` to `orjson.dumps(inputs).decode()` (orjson serializes dataclasses natively) |
| test_json_serializer.py | `tests/serializer/adapter/test_json_serializer.py` | Updated expected string to orjson's compact (no-space) formatting |

## agent-toolbox

| File | Path | What changed |
|---|---|---|
| tool_outcome.py | `src/agent_toolbox/domain/model/tool_outcome.py` | `ToolOutcome[T]` generic (PEP 695), strictly either/or success/failure, dropped `.content` |
| tool_specification.py | `src/agent_toolbox/domain/model/tool_specification.py` | `output_type` field replaces `returns: str` |
| tool_port.py | `src/agent_toolbox/application/port/outbound/tool_port.py` | `ToolPort[T]` generic protocol |
| model/\_\_init\_\_.py | `src/agent_toolbox/adapter/outbound/file/model/__init__.py` | New package |
| file_read_result.py | `src/agent_toolbox/adapter/outbound/file/model/file_read_result.py` | New: discriminated union output model (`TextFileResult \| StructuredFileResult \| RowsFileResult \| LinesFileResult`) |
| file_write_result.py | `src/agent_toolbox/adapter/outbound/file/model/file_write_result.py` | New: output model |
| model/\_\_init\_\_.py | `src/agent_toolbox/adapter/outbound/sql/model/__init__.py` | New package |
| sql_query_result.py | `src/agent_toolbox/adapter/outbound/sql/model/sql_query_result.py` | New: output model |
| model/\_\_init\_\_.py | `src/agent_toolbox/adapter/outbound/code/model/__init__.py` | New package |
| python_execution_result.py | `src/agent_toolbox/adapter/outbound/code/model/python_execution_result.py` | New: output model |
| reader_tool.py | `src/agent_toolbox/adapter/outbound/file/reader_tool.py` | Builds a typed `FileReadResult` variant instead of `orjson.dumps`-ing a raw value |
| writer_tool.py | `src/agent_toolbox/adapter/outbound/file/writer_tool.py` | Builds a typed `FileWriteResult` |
| sql_tool.py | `src/agent_toolbox/adapter/outbound/sql/sql_tool.py` | Builds a typed `SqlQueryResult` |
| python_tool.py | `src/agent_toolbox/adapter/outbound/code/python_tool.py` | Builds a typed `PythonExecutionResult`; strictly either/or on failure (folds stdout into the error string) |
| tool_bridge.py | `src/agent_toolbox/adapter/outbound/code/tool_bridge.py` | Sandbox bridge wire format updated to match pycraftcore's native-value contract |
| tool_binder.py | `src/agent_toolbox/adapter/inbound/mcp/tool_binder.py` | `structured_output=True`; return annotation driven by `specification.output_type` |
| file_reader.py | `src/agent_toolbox/adapter/outbound/specification/file_reader.py` | `output_type=FileReadResult` replaces hand-written `returns=` prose |
| file_writer.py | `src/agent_toolbox/adapter/outbound/specification/file_writer.py` | `output_type=FileWriteResult` |
| user_database.py | `src/agent_toolbox/adapter/outbound/specification/user_database.py` | `output_type=SqlQueryResult` |
| python_sandbox.py | `src/agent_toolbox/adapter/outbound/specification/python_sandbox.py` | `output_type=PythonExecutionResult`; tools-description wording tweak |
| toolbox_di.py | `src/bootstrap/di/toolbox_di.py` | `_tool_signature`/`_shape`/`_field_list`: schema-derived field hint (incl. discriminated-union variants) shown to the sandbox LLM before it writes code |
| pyproject.toml | `pyproject.toml` | `pycraftcore>=1.3.0`; temporary `[tool.uv.sources]` local path override to `../pycraftcore` |
| test_tool_outcome.py | `tests/agent_toolbox/domain/model/test_tool_outcome.py` | Rewritten for the generic, strictly either/or outcome |
| test_tools.py | `tests/agent_toolbox/adapter/outbound/test_tools.py` | Updated assertions for typed outputs across all four tools |
| test_tool_binder.py | `tests/agent_toolbox/adapter/inbound/test_tool_binder.py` | Added output-schema / structured-content coverage |
| test_specifications.py | `tests/agent_toolbox/adapter/outbound/specification/test_specifications.py` | Asserts `output_type` instead of `returns` |
| test_toolbox_di.py | `tests/bootstrap/di/test_toolbox_di.py` | Added `_shape`/`_tool_signature` coverage |

## agent-orchestrator

| File | Path | What changed |
|---|---|---|
| mcp_tool.py | `src/agent_orchestrator/adapter/outbound/tool/mcp/mcp_tool.py` | Prefers `result.structured_content` (JSON-dumped) over the text-block join; falls back to text on absence/error |
| test_mcp_tool_invoke.py | `tests/agent_orchestrator/adapter/outbound/test_mcp_tool_invoke.py` | New: real MCP server (real HTTP, not mocked) exercising structured/unstructured/error paths |
