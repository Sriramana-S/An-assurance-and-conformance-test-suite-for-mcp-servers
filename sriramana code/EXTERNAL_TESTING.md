# External Testing And Enhanced Reporting

This document consolidates the external server testing, comparative reporting,
complete workflow, and enhanced reporting guides.

## Overview

External testing lets the suite evaluate one or more MCP-compatible servers from
configuration and generate side-by-side compliance reports. It is useful for:

- comparing local, staging, production, official SDK, and community servers
- tracking compliance regressions
- identifying common and unique failures
- exporting results for stakeholders or CI/CD
- pairing compliance output with benchmark output for broader analysis

## Quick Start

Create an endpoint config:

```powershell
python test_external.py --create-sample-config config/my_endpoints.json
```

Edit the config, then run:

```powershell
python test_external.py --config config/my_endpoints.json --output-dir reports/comparative
```

Open or inspect:

```text
reports/comparative/
  comparison_report.html
  comparison_report.json
  comparison_report.csv
  batch_results.json
  individual_results/
```

Single endpoint:

```powershell
python test_external.py `
  --endpoint http://server.com/mcp `
  --endpoint-name "My Server" `
  --output-dir reports/external
```

List endpoints in a config:

```powershell
python test_external.py --config config/endpoints_example.json --list-endpoints
```

## Endpoint Config

```json
{
  "endpoints": [
    {
      "name": "Local Development",
      "url": "http://localhost:8000",
      "description": "Local MCP server",
      "protocol": "http",
      "timeout": 30,
      "skip_ssl_verify": false,
      "metadata": {
        "type": "development",
        "version": "sample"
      }
    },
    {
      "name": "Production",
      "url": "https://api.company.com/mcp",
      "description": "Production MCP server",
      "protocol": "http",
      "timeout": 60,
      "skip_ssl_verify": false,
      "metadata": {
        "type": "production"
      }
    }
  ],
  "testing_options": {
    "max_retries": 3,
    "timeout_seconds": 30,
    "skip_ssl_verification": false,
    "parallel_testing": false
  },
  "report_options": {
    "generate_json": true,
    "generate_html": true,
    "generate_csv": true,
    "include_metrics": true,
    "include_failure_analysis": true
  }
}
```

Endpoint fields:

| Field | Default | Description |
| --- | --- | --- |
| `name` | required | Server identifier |
| `url` | required | Endpoint URL |
| `description` | none | Human-readable description |
| `protocol` | `http` | Protocol label |
| `timeout` | `30` | Request timeout in seconds |
| `skip_ssl_verify` | `false` | Development-only SSL verification bypass |
| `metadata` | `{}` | Custom tags for environment, version, owner, or type |

The shared `ServerEndpoint` model also has a `command` field for STDIO command
targets. The single-target runner supports STDIO directly through
`main.py --transport stdio --command ...`; the current external-test CLI loader
is primarily HTTP-oriented.

## CLI Reference

```powershell
# Test one endpoint
python test_external.py --endpoint http://example.com/mcp --endpoint-name "Example"

# Test endpoints from config
python test_external.py --config config/endpoints_example.json --output-dir reports/comparative

# Create sample config
python test_external.py --create-sample-config config/my_endpoints.json

# List configured endpoints
python test_external.py --config config/endpoints_example.json --list-endpoints

# Help
python test_external.py --help
```

## Core Components

`core.external_client.ServerEndpoint`:

- endpoint metadata
- protocol label
- timeout and SSL options
- custom metadata

`core.external_client.ExternalMCPClient`:

- wraps HTTP/STDIO client creation
- adds retry logic and exponential backoff
- records request count, success/error count, response times, and success rate
- tracks session duration

`core.batch_runner.BatchTestRunner`:

- tests each endpoint
- aggregates results
- saves `batch_results.json`
- saves `individual_results/`

`core.comparison_reporter.ComparisonReportGenerator`:

- writes JSON, HTML, and CSV comparison reports
- compares overall and category scores
- surfaces common and unique failures

## Report Files

| File | Purpose |
| --- | --- |
| `comparison_report.html` | Visual dashboard with charts and tables |
| `comparison_report.json` | Machine-readable comparison |
| `comparison_report.csv` | Spreadsheet import |
| `batch_results.json` | Raw batch testing summary |
| `individual_results/` | Per-server JSON files |

HTML report sections:

- summary cards for total endpoints, average score, and duration
- compliance score bar chart
- category score chart for protocol, functional, and security results
- detailed comparison table
- common and unique failure analysis

JSON report shape:

```json
{
  "report_type": "comparative_compliance",
  "generated": "2026-06-01T17:30:00",
  "summary": {
    "total_endpoints": 3,
    "average_score": 87.5,
    "best_performer": "Server A",
    "best_score": 100.0,
    "worst_performer": "Server C",
    "worst_score": 75.0,
    "duration_seconds": 45.3
  },
  "compliance_comparison": [],
  "failure_analysis": {}
}
```

CSV columns include endpoint, URL, overall score, protocol score, functional
score, security score, tests passed, and tests failed.

## Metrics And Score Interpretation

Collected per endpoint:

- request count
- success count
- error count
- minimum, maximum, and average response time
- success rate
- session duration

Score ranges from the old quick reference:

| Score | Interpretation |
| --- | --- |
| 90-100% | Excellent compliance |
| 80-89% | Good compliance |
| 60-79% | Acceptable compliance |
| Below 60% | Poor compliance |

Failure analysis:

- common failures appear in multiple servers and can indicate a systematic
  implementation or specification issue
- unique failures appear in one server and usually indicate endpoint-specific
  configuration or implementation behavior

## Examples

Compare local and production:

```powershell
@'
{
  "endpoints": [
    {
      "name": "Local Development",
      "url": "http://localhost:8000"
    },
    {
      "name": "Production",
      "url": "https://api.company.com/mcp"
    }
  ]
}
'@ | Set-Content config/comparison.json

python test_external.py --config config/comparison.json --output-dir reports/comparison
```

Compare local sample, official SDK target, and non-compliant server:

```powershell
# Terminal 1
python -m sample_server.app

# Terminal 2
python -m sample_server.official_sdk_target

# Terminal 3
python run_non_compliant.py --violations missing_jsonrpc

# Terminal 4
python test_external.py --config config/endpoints_example.json --output-dir reports/comparative
```

CI threshold check:

```powershell
python test_external.py --config config/endpoints.json --output-dir reports/ci
python -c "import json; data=json.load(open('reports/ci/comparison_report.json')); raise SystemExit(0 if data['summary']['average_score'] >= 80 else 1)"
```

## Programmatic API

```python
from pathlib import Path
from core.batch_runner import BatchTestRunner
from core.external_client import ServerEndpoint
from core.comparison_reporter import ComparisonReportGenerator

endpoints = [
    ServerEndpoint("Server 1", "http://server1.com/mcp"),
    ServerEndpoint("Server 2", "http://server2.com/mcp"),
]

runner = BatchTestRunner(endpoints)
results = runner.run_batch()

reporter = ComparisonReportGenerator(results)
reporter.generate_json_report(Path("comparison_report.json"))
reporter.generate_html_report(Path("comparison_report.html"))
reporter.generate_csv_report(Path("comparison_report.csv"))

print(f"Average score: {results.average_score()}%")
print(f"Best: {results.best_performer().endpoint.name}")
```

Custom failure inspection:

```python
for endpoint_result in results.endpoints_tested:
    print(endpoint_result.endpoint.name)
    for test in endpoint_result.test_results:
        if test.status == "FAIL":
            print(f"  {test.category}: {test.name} - {test.message}")
```

## Enhanced Reporting

`generate_reports.py` takes existing compliance and/or benchmark JSON outputs
and writes enhanced JSON artifacts.

Enhanced compliance report:

```powershell
python generate_reports.py `
  --compliance reports/comparative/comparison_report.json `
  --output reports/enhanced_compliance
```

Enhanced benchmark report:

```powershell
python generate_reports.py `
  --benchmark reports/benchmark/benchmark_results.json `
  --output reports/enhanced_benchmark
```

Unified analysis:

```powershell
python generate_reports.py `
  --compliance reports/comparative/comparison_report.json `
  --benchmark reports/benchmark/benchmark_results.json `
  --output reports/unified `
  --unified
```

Generate all available enhanced outputs:

```powershell
python generate_reports.py `
  --compliance reports/comparative/comparison_report.json `
  --benchmark reports/benchmark/benchmark_results.json `
  --output reports/complete `
  --all
```

Current CLI output files:

| File | Description |
| --- | --- |
| `compliance_enhanced.json` | Compliance data plus enhancement flags |
| `benchmark_enhanced.json` | Benchmark data plus enhancement flags |
| `unified_analysis.json` | Combined compliance and benchmark JSON payload |

The unified reporting design preserved in `core.unified_reporter` includes:

- failure categorization
- recommendation generation
- performance recommendations
- comparison recommendations
- holistic compliance/performance scoring
- HTML report generation helpers

## Recommendation Model

The archived enhanced-reporting docs defined these recommendation categories.
They are retained here as the intended analysis model.

Compliance recommendations:

| Trigger | Severity | Action |
| --- | --- | --- |
| Protocol violations | High | Review MCP/JSON-RPC requirements and fix response/request behavior |
| Functional issues | Medium | Implement or correct required MCP methods |
| Security issues | Critical | Fix malformed-input handling and unsafe behavior |
| Perfect compliance | Info | Continue monitoring for regressions |

Performance recommendations:

| Trigger | Severity | Action |
| --- | --- | --- |
| Average response time over 500 ms | Medium | Profile hot paths, optimize code, consider caching |
| P99 latency over 2000 ms | High | Investigate slow queries and tail-latency causes |
| Throughput below 10 req/s | Medium | Increase concurrency or add connection pooling |
| Success rate below 100% | High | Investigate errors and improve resilience |
| Success rate at least 99.9% | Info | Maintain current practices |

Comparison recommendations:

| Trigger | Severity | Action |
| --- | --- | --- |
| Slowest server is more than 2x slower than fastest | Medium | Investigate implementation differences |
| Server outperforms average by 1.5x | Info | Use as an optimization reference |

Failure categories:

- protocol errors: JSON-RPC violations, MCP version mismatches, schema failures
- timeout errors: connection and request timeouts
- validation errors: invalid parameters, type mismatches, schema violations
- functional errors: missing methods, not implemented features, incorrect
  responses
- other errors: miscellaneous or uncategorized failures

Severity levels:

| Level | Meaning | Action |
| --- | --- | --- |
| Critical | Security or major functionality issue | Address immediately |
| High | Significant compliance/performance problem | Address soon |
| Medium | Notable quality or user-experience issue | Address in next iteration |
| Info | Positive feedback or monitoring note | Review and track |

## Complete Workflow

```powershell
# 1. Run compliance comparison
python test_external.py --config config/endpoints.json --output-dir reports/compliance

# 2. Run performance benchmark
python benchmark_external.py --config config/endpoints.json --iterations 50 --output reports/benchmark

# 3. Generate unified JSON analysis
python generate_reports.py `
  --compliance reports/compliance/comparison_report.json `
  --benchmark reports/benchmark/benchmark_results.json `
  --output reports/final `
  --all
```

Data flow:

```text
Endpoint config
  -> compliance testing
  -> comparison_report.json

Endpoint config
  -> benchmarking
  -> benchmark_results.json

comparison_report.json + benchmark_results.json
  -> generate_reports.py
  -> enhanced/unified JSON reports
```

## CI/CD And Scheduled Use

GitHub Actions sketch:

```yaml
- name: Test External MCP Servers
  run: python test_external.py --config config/endpoints.json --output-dir reports/comparative

- name: Benchmark MCP Servers
  run: python benchmark_external.py --config config/endpoints.json --output reports/benchmark

- name: Generate Enhanced Reports
  run: |
    python generate_reports.py \
      --compliance reports/comparative/comparison_report.json \
      --benchmark reports/benchmark/benchmark_results.json \
      --output reports/enhanced \
      --all
```

Scheduled PowerShell-style run:

```powershell
$date = Get-Date -Format yyyy-MM-dd
$output = "reports/$date"
python test_external.py --config config/endpoints.json --output-dir "$output/compliance"
python benchmark_external.py --config config/endpoints.json --output "$output/benchmark"
python generate_reports.py `
  --compliance "$output/compliance/comparison_report.json" `
  --benchmark "$output/benchmark/benchmark_results.json" `
  --output "$output/enhanced" `
  --all
```

## Troubleshooting

Connection failure:

```powershell
curl -X POST http://server.com/mcp `
  -H "Content-Type: application/json" `
  -d '{"jsonrpc":"2.0","method":"ping","id":1}'
```

SSL certificate error:

```json
{
  "endpoints": [
    {
      "name": "Development Server",
      "url": "https://server.com/mcp",
      "skip_ssl_verify": true
    }
  ]
}
```

Timeout:

```json
{
  "endpoints": [
    {
      "name": "Slow Server",
      "url": "http://slow.example.com/mcp",
      "timeout": 60
    }
  ]
}
```

Missing enhanced recommendations:

- ensure the input JSON has test failures and messages
- verify paths point to the generated result files
- check that the output directory is writable

## Best Practices

- Use consistent endpoint names so reports can be compared over time.
- Keep configs in version control, but treat generated reports as potentially
  sensitive because they may contain failure details.
- Run external compliance before benchmarking so protocol failures do not get
  mistaken for performance problems.
- Store report output by date for manual trend comparison.
- Share HTML/CSV comparison reports with stakeholders and JSON reports with
  automation.

## Limitations

- External CLI testing is sequential in the current implementation.
- Generated reports can include sensitive endpoint and failure details.
- Historical trend analysis is manual unless you add external storage/scripts.
- `generate_reports.py` currently writes enhanced JSON/unified JSON artifacts;
  richer HTML unified reporting is represented in `core.unified_reporter`.
