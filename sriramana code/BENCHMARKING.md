# MCP Server Benchmarking

The benchmarking system measures and compares MCP server performance. It
complements compliance testing by answering how fast, reliable, and load-tolerant
each server is.

## What It Measures

- throughput in requests per second
- response time min, max, average, median, p95, p99, and standard deviation
- success and error rates
- method-by-method performance
- stress-test degradation as request rate increases
- comparative rankings across servers

## Quick Start

Single server:

```powershell
python benchmark_external.py --url http://localhost:8000 --name "My Server"
```

Multiple servers from config:

```powershell
python benchmark_external.py --config config/endpoints_example.json --output reports/benchmark
```

Stress test:

```powershell
python benchmark_external.py `
  --config config/endpoints_example.json `
  --stress-test `
  --duration 60 `
  --initial-rps 1 `
  --max-rps 500 `
  --output reports/stress
```

List endpoints:

```powershell
python benchmark_external.py --config config/endpoints_example.json --list
```

Generate an example config:

```powershell
python benchmark_external.py --generate-config config/endpoints_example.json
```

## CLI Options

| Option | Default | Description |
| --- | --- | --- |
| `--url` | none | Single server URL |
| `--name` | derived from URL | Name for single-server report files |
| `--config` | none | JSON file containing endpoints |
| `--output` | `benchmark_reports` | Output directory |
| `--iterations` | `10` | Iterations per standard MCP method |
| `--format` | `all` | `all`, `json`, `csv`, or `html` |
| `--stress-test` | false | Run load-ramp stress test instead of standard benchmark |
| `--method` | `tools/list` | MCP method used by stress test |
| `--duration` | `30` | Stress-test duration in seconds |
| `--initial-rps` | `1` | Starting request rate |
| `--max-rps` | `100` | Peak request rate |
| `--list` | false | List endpoints from `--config` |
| `--generate-config` | none | Write an example endpoint config |

## Endpoint Config

Minimal:

```json
{
  "endpoints": [
    {
      "name": "Server A",
      "url": "http://localhost:8000"
    },
    {
      "name": "Server B",
      "url": "http://localhost:8001"
    }
  ]
}
```

Full HTTP example:

```json
{
  "endpoints": [
    {
      "name": "Reference Server",
      "url": "http://localhost:8000",
      "timeout": 30,
      "skip_ssl_verify": false,
      "metadata": {
        "version": "1.0",
        "environment": "production",
        "type": "reference"
      }
    }
  ]
}
```

Fields:

- `name`: required server identifier.
- `url`: required HTTP endpoint.
- `timeout`: request timeout in seconds, default `30`.
- `skip_ssl_verify`: development-only SSL bypass flag.
- `metadata`: arbitrary tags for version, environment, or server type.

## Standard Benchmark

Standard mode runs a fixed number of iterations against the default MCP methods:

- `initialize`
- `tools/list`
- `resources/list`
- `prompts/list`

Example:

```powershell
python benchmark_external.py --config endpoints.json --iterations 50 --output reports/benchmark
```

Metrics collected:

- per-request response time in milliseconds
- min, max, average, median, p95, p99, standard deviation
- requests per second
- success rate and error rate
- raw error messages when requests fail

## Stress Testing

Stress mode gradually increases request rate over a fixed duration:

```powershell
python benchmark_external.py `
  --config endpoints.json `
  --stress-test `
  --method tools/list `
  --duration 120 `
  --initial-rps 1 `
  --max-rps 1000 `
  --output reports/stress
```

Use it to identify:

- response time degradation under load
- maximum practical throughput
- error rates at different load levels
- breaking points and overload behavior

Suggested progression:

```text
Light:  --duration 30  --max-rps 10
Medium: --duration 60  --max-rps 100
Heavy:  --duration 120 --max-rps 1000
```

## Output Files

Batch benchmark:

| File | Purpose |
| --- | --- |
| `benchmark_results.json` | Structured results for analysis or CI |
| `benchmark_results.csv` | Spreadsheet-compatible summary |
| `benchmark_results.html` | Interactive dashboard with charts |

Single-server benchmark:

| File | Purpose |
| --- | --- |
| `{name}_benchmark.json` | Single-server structured results |
| `{name}_benchmark.csv` | Single-server spreadsheet output |
| `{name}_benchmark.html` | Single-server HTML report |

Stress test:

| File | Purpose |
| --- | --- |
| `stress_test_results.json` | Structured stress-test data |
| `stress_test_results.csv` | Spreadsheet output |
| `stress_test_results.html` | Stress-test dashboard |

## Report Contents

HTML reports include:

- executive summary
- fastest and slowest server
- best throughput server
- average response-time chart
- throughput chart
- success-rate chart
- per-method statistics table

JSON reports include:

```json
{
  "benchmark_timestamp": "2024-01-15T10:30:00",
  "total_duration_seconds": 45.3,
  "servers_tested": 3,
  "results": [
    {
      "endpoint": {"name": "Server A", "url": "..."},
      "overall_stats": {
        "total_requests": 120,
        "success_rate": 100.0,
        "response_times_ms": {
          "avg": 45.23,
          "p95": 67.89,
          "p99": 89.01
        }
      }
    }
  ],
  "rankings": {
    "fastest": "Server A",
    "best_throughput": "Server B"
  }
}
```

CSV reports include server names, request counts, success/failure counts, success
rate, response time statistics, and throughput.

## Metric Interpretation

| Metric | Meaning |
| --- | --- |
| Min | Fastest single response |
| Max | Slowest single response |
| Average | Mean response time |
| Median/P50 | Typical response time |
| P95 | 95% of requests were faster than this |
| P99 | 99% of requests were faster than this |
| Standard deviation | Response-time consistency |
| Requests/second | Throughput |
| Success rate | Reliability under the benchmark conditions |

Signals:

- high standard deviation means inconsistent performance
- high P95/P99 means tail-latency risk
- low median plus high max means rare slowdowns
- success rate below 99% indicates reliability issues
- stress-test throughput that plateaus while latency rises suggests saturation

Typical ranges from archived quick reference:

| Environment | Response time | Throughput | Success rate |
| --- | --- | --- | --- |
| Local server | 5-50 ms | 100-1000 req/s | 100% |
| Remote server | 20-200 ms | 10-500 req/s | 99-100% |
| Under stress | May increase 2-10x | Rises then plateaus | May drop if overloaded |

## Programmatic API

```python
from pathlib import Path
from core.external_client import ServerEndpoint
from core.batch_benchmark import BatchBenchmarkRunner
from core.benchmark_reporter import BenchmarkReportGenerator

endpoints = [
    ServerEndpoint(name="Server A", url="http://localhost:8000"),
    ServerEndpoint(name="Server B", url="http://localhost:8001"),
]

runner = BatchBenchmarkRunner(endpoints)
comparison = runner.run_benchmarks(iterations_per_method=50)

reporter = BenchmarkReportGenerator(comparison)
output_dir = Path("reports/benchmark")
output_dir.mkdir(parents=True, exist_ok=True)
reporter.generate_json_report(output_dir / "benchmark_results.json")
reporter.generate_html_report(output_dir / "benchmark_results.html")
reporter.generate_csv_report(output_dir / "benchmark_results.csv")
```

Stress test API:

```python
comparison = runner.run_stress_tests(
    method="tools/list",
    duration_seconds=120,
    initial_rps=1,
    max_rps=1000,
)
```

Analyze results:

```python
fastest = comparison.fastest_server()
print(f"Fastest: {fastest.endpoint.name}")

times = comparison.average_response_time_by_method("tools/list")
for server, time_ms in times.items():
    print(f"{server}: {time_ms:.2f}ms")

for result in comparison.results:
    stats = result.get_overall_stats()
    print(f"{result.endpoint.name}: {stats.requests_per_second:.2f} req/s")
```

## Data Structures

`BenchmarkMetric`:

- `timestamp`
- `method`
- `response_time_ms`
- `success`
- `error_message`

`BenchmarkStatistics`:

- `total_requests`
- `successful_requests`
- `failed_requests`
- min/max/average/median/p95/p99/stdev response time
- `requests_per_second`
- `success_rate`
- `error_rate`

`ServerBenchmarkResult`:

- endpoint information
- raw metrics list
- per-method statistics
- total duration
- concurrent request count
- `get_overall_stats()`

`BenchmarkComparison`:

- list of server results
- benchmark timestamp
- total duration
- `fastest_server()`
- `slowest_server()`
- `best_throughput()`
- `highest_success_rate()`
- `average_response_time_by_method(method)`

## Integration With Compliance Testing

Run compliance and performance checks from the same endpoint list:

```powershell
python test_external.py --config endpoints.json --output-dir reports/compliance
python benchmark_external.py --config endpoints.json --output reports/benchmark
```

Then generate an enhanced/unified JSON report:

```powershell
python generate_reports.py `
  --compliance reports/compliance/comparison_report.json `
  --benchmark reports/benchmark/benchmark_results.json `
  --output reports/enhanced `
  --all
```

The non-compliant server can also be benchmarked at `http://127.0.0.1:8001`,
which is useful when comparing compliant and intentionally broken behavior.

## Troubleshooting

Connection refused or timeout:

```powershell
curl http://localhost:8000/
python benchmark_external.py --config config/endpoints_example.json --list
```

Slow or unrealistic results:

- run during quiet periods
- increase iterations with `--iterations 50` or higher
- repeat benchmarks and compare averages
- isolate network effects by testing locally
- check CPU and memory load during the run

SSL certificate errors:

```json
{
  "endpoints": [
    {
      "name": "Development Server",
      "url": "https://dev.example.com/mcp",
      "skip_ssl_verify": true
    }
  ]
}
```

Only bypass SSL verification for development/testing.

Missing output files:

- check output path and permissions
- pass an explicit path with `--output reports/benchmark`
- verify the command did not exit early because the config path was wrong

## Best Practices

- Test all servers under the same network and machine conditions.
- Use enough iterations for stable averages.
- Keep benchmark parameters with the generated reports.
- Use stress tests for capacity planning, not just normal comparisons.
- Establish baselines and rerun periodically.
- Compare compliance and performance together before drawing conclusions.

Monthly baseline example:

```powershell
python benchmark_external.py `
  --config endpoints.json `
  --output reports/baseline_2026-06 `
  --iterations 100
```

## Limitations

- Batch benchmarks are sequential for deterministic results.
- Results include network latency.
- Historical trending is not built in.
- Benchmark config loading is currently HTTP-oriented.
- The HTML benchmark report uses Chart.js for charts.

## Future Enhancements

Archived implementation notes proposed:

- historical trend comparisons
- optional parallel server benchmarking
- SLA thresholds and alerting
- saved performance profiles
- database persistence
- real-time dashboard
- automated regression detection
