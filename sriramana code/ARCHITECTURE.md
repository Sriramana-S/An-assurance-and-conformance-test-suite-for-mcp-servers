# MCP Assurance Suite Architecture

This document consolidates the former architecture, implementation-summary,
delivery, STDIO, and project-index notes into a single technical reference.

## System Overview

The suite is organized around a transport-neutral assurance pipeline:

```text
CLI/config
  -> BaseMCPClient implementation
  -> core.suite assurance cases
  -> ProtocolConformanceEngine and ProtocolValidator
  -> AssuranceResult models
  -> JSON/HTML/CSV reporters
```

The major feature areas are:

| Area | Entry point | Core modules |
| --- | --- | --- |
| Single-target assurance | `main.py` | `core.client`, `core.suite`, `core.reporter` |
| External comparison | `test_external.py` | `core.external_client`, `core.batch_runner`, `core.comparison_reporter` |
| Benchmarking | `benchmark_external.py` | `core.benchmark_engine`, `core.batch_benchmark`, `core.benchmark_reporter` |
| Enhanced/unified reports | `generate_reports.py` | `core.unified_reporter`, reporter modules |
| Violation testing | `run_non_compliant.py` | `sample_server.non_compliant`, assurance core |

## Core Assurance Pipeline

`main.py` loads `SuiteConfig`, applies CLI overrides, creates a transport
client, runs the assurance suite, collects transport metrics, and writes
reports.

Key responsibilities:

- `core.config.SuiteConfig`: JSON/environment-backed configuration.
- `core.client.BaseMCPClient`: shared request, notification, raw-payload, metric,
  and cleanup interface.
- `core.client.HttpMCPClient`: sends JSON-RPC payloads to HTTP endpoints with
  `requests.post()`.
- `core.client.StdioMCPClient`: starts a command with `subprocess.Popen()`,
  writes JSON-RPC lines to stdin, reads responses from stdout, tracks stderr,
  timeouts, malformed output, and cleanup.
- `core.suite.run_suite()`: executes reusable assurance cases against any
  `BaseMCPClient`.
- `core.conformance.ProtocolConformanceEngine`: validates JSON-RPC/MCP request
  and notification structure.
- `core.validator.ProtocolValidator`: validates response envelopes, initialize
  metadata, list schemas, error objects, and transport failures.
- `core.models`: typed response, result, validation, and transport metric models.
- `core.reporter.ReportGenerator`: prints the summary and writes
  `compliance_report.json` and `compliance_report.html`.

## Transport Abstraction

```text
BaseMCPClient
  send_request(method, params, request_id)
  send_notification(method, params)
  send_payload(payload)
  send_raw(raw_body)
  get_metrics()
  close()

HttpMCPClient(BaseMCPClient)
  HTTP JSON-RPC transport.

StdioMCPClient(BaseMCPClient)
  Command-backed line-oriented JSON-RPC transport.
```

`MCPClient` remains a backward-compatible alias for `HttpMCPClient`.

HTTP usage:

```python
from core.client import HttpMCPClient

client = HttpMCPClient("http://localhost:8000")
```

STDIO usage:

```python
from core.client import StdioMCPClient
from core.suite import run_suite

client = StdioMCPClient("python -m sample_server.stdio_app")
results = run_suite(client, "2025-11-25")
client.close()
```

Transport metrics recorded for reports:

- transport type
- request count
- success count
- failure count
- average response time
- minimum response time
- maximum response time
- failure rate

## Assurance Cases

The suite validates:

- initialize handshake
- initialized notification
- JSON-RPC version and request id behavior
- `tools/list`, `resources/list`, `prompts/list`
- advertised tool execution
- malformed and invalid protocol inputs
- method-not-found handling
- declared capability consistency

Categories map to protocol conformance, functional correctness, security
validation, and interoperability.

## Reporting Architecture

Single-target reports:

```text
ReportGenerator
  -> print_report()
  -> save_json_report()
  -> save_html_report()
```

Comparative compliance reports:

```text
BatchTestRunner
  -> BatchTestResults
  -> ComparisonReportGenerator
       -> comparison_report.json
       -> comparison_report.html
       -> comparison_report.csv
```

Benchmark reports:

```text
BatchBenchmarkRunner
  -> BenchmarkComparison
  -> BenchmarkReportGenerator
       -> benchmark_results.json
       -> benchmark_results.html
       -> benchmark_results.csv
```

Enhanced report generation:

```text
generate_reports.py
  -> compliance_enhanced.json
  -> benchmark_enhanced.json
  -> unified_analysis.json
```

`core.unified_reporter` contains the design for richer unified analysis:
recommendations, failure categorization, holistic scoring, and HTML generation.
The current CLI materializes enhanced JSON and unified JSON from existing result
files.

## External Testing Components

`core.external_client.ServerEndpoint` represents an endpoint:

```python
ServerEndpoint(
    name="Server",
    url="http://localhost:8000",
    command=None,
    description="Optional",
    protocol="http",
    timeout=30,
    skip_ssl_verify=False,
    metadata={},
)
```

`ExternalMCPClient` wraps the transport client with:

- endpoint metadata
- automatic retry up to three attempts
- exponential backoff
- performance metric collection
- session duration tracking

`BatchTestRunner` coordinates multi-server testing:

- tests endpoints sequentially
- continues after endpoint failures
- aggregates pass/fail counts and category scores
- persists batch and individual results
- supports common/unique failure analysis through the reporter

## Benchmarking Components

`core.benchmark_engine` contains:

- `BenchmarkMetric`: timestamp, method, response time, success flag, error
  message.
- `BenchmarkStatistics`: total/success/failed counts, min/max/average/median,
  p95, p99, standard deviation, throughput, success/error rates.
- `ServerBenchmarkResult`: endpoint, raw metrics, per-method statistics, total
  duration, concurrent request count.
- `ServerBenchmark`: single-server standard benchmark and stress test execution.

`core.batch_benchmark` contains:

- `BenchmarkComparison`: aggregates server results, exposes fastest/slowest,
  best throughput, highest success rate, and method-specific comparisons.
- `BatchBenchmarkRunner`: runs standard benchmarks and stress tests across all
  configured endpoints.

Benchmarking is intentionally sequential for deterministic comparisons. It does
not retry during benchmark measurement so the timings reflect observed behavior.

## Non-Compliant Server Architecture

The violation test server lives in `sample_server/non_compliant.py` and is
started by `run_non_compliant.py`.

Design:

```text
Request
  -> request parsing
  -> session/lifecycle checks
  -> VIOLATIONS dictionary lookup
  -> response builder injection
  -> JSON-RPC response
```

Main components:

- `VIOLATIONS`: global dictionary of toggles.
- response builders: apply envelope, id, result, error, and content-shape
  violations.
- session state: tracks initialization status and used request ids.
- CLI runner: enables named violations, lists violations, and starts on port
  `8001`.

Design decisions preserved from the implementation notes:

- Global violation flags were chosen for simple runtime toggling.
- Response-builder injection gives direct control over exact protocol breaks.
- Port `8001` avoids conflicts with the compliant sample on `8000`.
- Flask matches the existing sample server and keeps dependencies simple.

## Configuration Flow

Default single-target config:

```text
config/default.json
  -> SuiteConfig.from_file()
  -> CLI/env overrides
  -> create_client()
  -> run_suite()
```

Endpoint-list config:

```text
config/endpoints_example.json
  -> ServerEndpoint list
  -> BatchTestRunner or BatchBenchmarkRunner
  -> reporter
```

Supported endpoint fields:

| Field | Purpose |
| --- | --- |
| `name` | Human-readable server identifier |
| `url` | HTTP URL or logical STDIO URI |
| `command` | STDIO command for programmatic `ServerEndpoint` use |
| `description` | Optional description |
| `protocol` | `http` or `stdio` |
| `timeout` | Per-request timeout in seconds |
| `skip_ssl_verify` | Development-only SSL bypass flag |
| `metadata` | Custom tags such as version, environment, or server type |

Current caveat: the single-target runner fully supports STDIO through
`--transport stdio --command ...`. The external and benchmark CLI config
loaders are primarily HTTP-oriented; use programmatic endpoint construction when
passing command-backed STDIO endpoints through those paths.

## Complete Workflow

```text
1. Compliance testing
   python test_external.py --config config/endpoints.json --output-dir reports/compliance

2. Benchmarking
   python benchmark_external.py --config config/endpoints.json --output reports/benchmark

3. Enhanced reporting
   python generate_reports.py \
     --compliance reports/compliance/comparison_report.json \
     --benchmark reports/benchmark/benchmark_results.json \
     --output reports/enhanced \
     --all

4. Review reports and act on failures, performance gaps, and recommendations.
```

## Testing Strategy

Verification is layered:

- unit and conformance tests for request/response validation
- HTTP integration through `sample_server.app`
- STDIO integration through `sample_server.stdio_app`
- external comparison through `test_external.py`
- non-compliant server violation tests
- benchmark import/config/report generation checks

Verified commands recorded in the old docs:

```powershell
python -m py_compile ...
python -m pytest -q
python main.py
python main.py --transport stdio --command "python -m sample_server.stdio_app"
```

## Extension Notes

Useful future enhancements from the archived docs:

- historical report trending
- optional parallel benchmark execution
- SLA thresholds and alerting
- long-term database persistence
- live dashboard for benchmark runs
- runtime API for enabling/disabling non-compliant server violations
- STDIO variant of the non-compliant server
- randomized violation injection for robustness testing
