# MCP Assurance Suite

![Conformance](https://github.com/YOUR_USERNAME/mcp-assurance-suite/actions/workflows/conformance.yml/badge.svg)

An automated assurance, conformance, comparison, and benchmarking suite for
Model Context Protocol (MCP) servers. It sends JSON-RPC requests to MCP targets,
validates protocol and feature behavior, and generates JSON/HTML/CSV reports.

The suite covers:

- protocol compliance
- functional testing
- basic security validation
- interoperability checks
- external server comparison
- performance benchmarking
- automated reporting

## Reproducing the Results

Prerequisites:

- Python 3.11
- Node.js 18+ (for `npx`, used by the real-world survey)
- `pip install -r requirements.txt`

Pinned versions of the key dependencies used to produce these results:

| Package | Version |
| --- | --- |
| pytest | 9.0.3 |
| hypothesis | 6.155.2 |
| requests | 2.32.4 |
| Flask | 3.1.3 |

**Command 1 — reproduce the 52-test passing run:**

```powershell
python -m pytest tests/ -v
```

**Command 2 — reproduce the local 100% MUST-compliance baseline (34 assurance cases):**

```powershell
# Terminal 1 — start the compliant sample server
python -m sample_server.app

# Terminal 2 — run the conformance suite against it
python main.py --server-url http://127.0.0.1:8000
```

**Command 3 — reproduce the empirical real-world survey:**

```powershell
python survey.py
```

**Command 4 — run differential interoperability testing:**

```powershell
python differential.py --compare-sdks
```

**Command 5 — generate aggregate analysis and charts:**

```powershell
python survey_analysis.py
```

## Documentation

Only the durable documentation is kept at the project root:

| File | Purpose |
| --- | --- |
| `README.md` | Setup, common commands, project map, and non-compliant server usage |
| `ARCHITECTURE.md` | Component design, transport abstraction, data flow, and extension notes |
| `BENCHMARKING.md` | Performance benchmark CLI, configuration, metrics, reports, and API usage |
| `EXTERNAL_TESTING.md` | Multi-server testing, comparative reports, and enhanced report generation |

Older guide, quick reference, start, delivery, and summary documents were merged
into these files and archived under `archive/docs_archive/`.

## Project Structure

```text
core/
  client.py              BaseMCPClient, HttpMCPClient, StdioMCPClient
  conformance.py         Session-aware conformance engine
  validator.py           JSON-RPC and MCP response validators
  suite.py               Reusable transport-neutral assurance cases
  reporter.py            Single-target JSON/HTML report generation
  external_client.py     Endpoint model, retry wrapper, performance metrics
  batch_runner.py        Multi-server compliance orchestration
  comparison_reporter.py Comparative JSON/HTML/CSV reports
  benchmark_engine.py    Request timing and benchmark statistics
  batch_benchmark.py     Multi-server benchmark orchestration
  benchmark_reporter.py  Benchmark JSON/HTML/CSV reports
  unified_reporter.py    Unified compliance/benchmark reporting helpers

sample_server/
  app.py                 Local HTTP MCP-style sample server
  stdio_app.py           Local STDIO MCP-style sample server
  official_sdk_target.py Comparative HTTP target using the official MCP SDK
  non_compliant.py       Deliberately broken server for violation testing

config/
  default.json           Default local evaluation config
  endpoints_example.json Example multi-endpoint config

reports/
  local_sample/          Passing local sample report
  official_sdk_target/   Comparative official-SDK target report
  evidence/              Saved console/server artifacts

main.py                  Single-target assurance runner
test_external.py         Multi-server compliance comparison CLI
benchmark_external.py    Multi-server benchmark CLI
generate_reports.py      Enhanced JSON/unified report CLI
run_non_compliant.py     Non-compliant sample server launcher
Dockerfile               Optional containerized runner
pytest.ini               Pytest discovery config
```

## Local Quick Start

From PowerShell:

```powershell
cd C:\Projects\mcp-assurance-suite
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

By default, `python main.py` auto-starts the local sample server from
`sample_server/app.py`, tests `http://127.0.0.1:8000`, and writes:

- `reports/local_sample/compliance_report.html`
- `reports/local_sample/compliance_report.json`

Expected local result:

```text
Overall MUST Compliance Score: 100.0%
Passed: 34 | Failed: 0 | Warned: 0 | Skipped: 0
```

If the sample server is already running, `main.py` detects it and reuses the
existing process.

## Two-Terminal Local Mode

Terminal 1:

```powershell
cd C:\Projects\mcp-assurance-suite
.\.venv\Scripts\activate
python -m sample_server.app
```

Terminal 2:

```powershell
cd C:\Projects\mcp-assurance-suite
.\.venv\Scripts\activate
python main.py
```

## Run Pytest

```powershell
python -m pytest -q
```

Current verification recorded by the previous docs:

```text
52 passed
HTTP sample: 34 assurance cases, 100.0% overall (34 PASS)
STDIO sample: 34 assurance cases, 100.0% overall (30 PASS, 4 HTTP-only auth cases skipped)
```

## Run A Specific Target

HTTP target:

```powershell
python main.py --transport http --server-url http://localhost:8000
```

Different HTTP endpoint:

```powershell
python main.py --server-url http://127.0.0.1:8010/mcp --output-dir reports/official_sdk_target
```

Included official-SDK comparison target:

```powershell
# Terminal 1
python -m sample_server.official_sdk_target

# Terminal 2
python main.py --server-url http://127.0.0.1:8010/mcp --output-dir reports/official_sdk_target
```

This produces:

- `reports/official_sdk_target/compliance_report.html`
- `reports/official_sdk_target/compliance_report.json`
- `reports/evidence/official_sdk_console.txt`

## STDIO Targets

The suite supports HTTP and STDIO through a shared client interface.

Local STDIO sample:

```powershell
python main.py --transport stdio --command "python -m sample_server.stdio_app"
```

Docker STDIO example:

```powershell
python main.py --transport stdio --command "docker run -i mcp/time"
```

Existing HTTP code can continue using `MCPClient`, which is kept as an alias for
`HttpMCPClient`. For new code, prefer explicit transport clients from
`core.client`.

## Multi-Server And Benchmark Workflows

Comparative compliance testing:

```powershell
python test_external.py --config config/endpoints_example.json --output-dir reports/comparative
```

Benchmarking:

```powershell
python benchmark_external.py --config config/endpoints_example.json --output reports/benchmark
```

Generate enhanced/unified JSON reports from existing result files:

```powershell
python generate_reports.py `
  --compliance reports/comparative/comparison_report.json `
  --benchmark reports/benchmark/benchmark_results.json `
  --output reports/enhanced `
  --all
```

See `EXTERNAL_TESTING.md` and `BENCHMARKING.md` for details.

## Non-Compliant Server

The project includes a deliberately non-compliant MCP server for validating that
the assurance framework detects protocol violations. It runs on port `8001` so
it can be used alongside the normal sample server on port `8000`.

Start a compliant baseline using the same implementation with no violations:

```powershell
python run_non_compliant.py
python main.py --server-url http://127.0.0.1:8001 --output-dir reports/non_compliant_baseline
```

Expected baseline:

```text
Overall MUST Compliance Score: 100.0%
Passed: 34 | Failed: 0 | Warned: 0 | Skipped: 0
```

Enable one violation:

```powershell
python run_non_compliant.py --violations missing_jsonrpc
python main.py --server-url http://127.0.0.1:8001 --output-dir reports/test_missing_jsonrpc
```

Recorded expected result:

```text
Overall MUST Compliance Score: 25.0%
Passed: 7 | Failed: 21 | Warned: 6 | Skipped: 0
```

Enable multiple violations:

```powershell
python run_non_compliant.py --violations missing_jsonrpc invalid_jsonrpc_version missing_id
python main.py --server-url http://127.0.0.1:8001 --output-dir reports/test_multi_violation
```

List available violations:

```powershell
python run_non_compliant.py --list-violations
```

### Violation Catalog

| Category | Violations |
| --- | --- |
| JSON-RPC | `missing_jsonrpc`, `invalid_jsonrpc_version`, `both_result_and_error`, `neither_result_nor_error`, `missing_id`, `invalid_id_type`, `mismatched_id` |
| MCP protocol | `invalid_initialize_response`, `missing_server_name`, `missing_server_version`, `invalid_protocol_version_type`, `missing_capabilities`, `invalid_tools_list`, `invalid_resources_list`, `invalid_prompts_list` |
| Lifecycle/state | `skip_lifecycle_check`, `reuse_request_ids`, invalid state transitions such as operations before `notifications/initialized` |
| Error handling | `invalid_error_object`, `invalid_error_code_type`, `empty_error_message`, `invalid_error_code` |
| Content shape | `non_object_result` |
| Authorization (HTTP §2.4/§6.3) | `missing_version_header`, `missing_oauth_discovery` |

Recorded scenario scores (34 cases per run; MUST score =
passed / (passed + failed) x 100, WARN and SKIP excluded):

| Violation | Passed | Failed | Warned | Skipped | MUST Score |
| --- | ---: | ---: | ---: | ---: | ---: |
| No violations (clean baseline) | 34 | 0 | 0 | 0 | 100.0% |
| `missing_jsonrpc` | 7 | 21 | 6 | 0 | 25.0% |
| `invalid_jsonrpc_version` | 8 | 20 | 6 | 0 | 28.57% |
| `invalid_initialize_response` | 16 | 12 | 6 | 0 | 57.14% |
| `missing_server_name` | 18 | 12 | 4 | 0 | 60.0% |
| `invalid_tools_list` | 31 | 3 | 0 | 0 | 91.18% |
| `invalid_resources_list` | 31 | 3 | 0 | 0 | 91.18% |
| `invalid_resources_read` | 33 | 1 | 0 | 0 | 97.06% |
| `invalid_prompts_get` | 33 | 1 | 0 | 0 | 97.06% |
| `invalid_error_object` | 23 | 9 | 2 | 0 | 71.88% |
| `missing_capabilities` | 18 | 12 | 4 | 0 | 60.0% |
| `reuse_request_ids` | 34 | 0 | 0 | 0 | 100.0% |
| `missing_version_header` | 33 | 0 | 1 | 0 | 100.0% |
| `missing_oauth_discovery` | 33 | 0 | 1 | 0 | 100.0% |

Troubleshooting:

```powershell
# Check port 8001
netstat -ano | findstr :8001

# Check server health
curl http://127.0.0.1:8001/

# Verify imports
python -c "from sample_server.non_compliant import app; print('OK')"
```

## Proposal Mapping

| Proposal area | Implementation |
| --- | --- |
| Protocol compliance | Session-aware conformance engine, `initialize`, initialized notification, JSON-RPC version/id checks, method-not-found checks |
| Functional testing | `tools/list`, `resources/list`, `prompts/list`, advertised tool execution |
| Security validation | Null method, numeric method, empty method, missing/invalid JSON-RPC version, malformed JSON, missing fields, invalid params |
| Interoperability | String request-id echo and declared capability consistency |
| Automated reporting | JSON/HTML reports with protocol, functional, security, interoperability, transport metrics, and overall compliance scores |

## Evidence

Generated reports are runtime artifacts. Previous local, STDIO, external-target,
official-SDK, and evidence reports were moved to `archive/reports/` during the
production cleanup. New runs recreate `reports/` outputs as needed.

The comparative report is useful even when checks fail: it shows that the
framework can evaluate another MCP-compatible target and surface behavioral
differences in protocol and error handling.

## Docker

Docker is optional:

```powershell
docker build -t mcp-assurance-suite .
docker run --rm -v ${PWD}/reports:/app/reports mcp-assurance-suite
```

Local Python execution is the verified path on the current machine.

## Scope And Limitations

- The main runner supports HTTP JSON-RPC and STDIO JSON-RPC MCP targets.
- External comparison and benchmark CLIs are primarily HTTP-oriented in their
  current argument loaders; use `main.py --transport stdio --command ...` for
  direct STDIO assurance runs.
- Security testing is intentionally basic and focuses on safe rejection of
  malformed protocol inputs, not authentication, authorization, or adversarial
  penetration testing.
- Historical trend storage, SLA alerting, and long-term report persistence are
  future enhancements rather than built-in services.
