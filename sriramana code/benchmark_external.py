#!/usr/bin/env python3
"""
CLI tool for benchmarking external MCP servers.
Supports single-server benchmarks, batch testing, stress testing, and comparative reporting.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from core.external_client import ServerEndpoint
from core.batch_benchmark import BatchBenchmarkRunner
from core.benchmark_reporter import BenchmarkReportGenerator


def load_endpoints_from_config(config_file: Path) -> List[ServerEndpoint]:
    """Load endpoints from JSON configuration."""
    with open(config_file, 'r') as f:
        config = json.load(f)
    
    endpoints = []
    for endpoint_config in config.get('endpoints', []):
        endpoint = ServerEndpoint(
            name=endpoint_config.get('name', 'Unknown'),
            url=endpoint_config.get('url'),
            command=endpoint_config.get('command'),
            protocol=endpoint_config.get('protocol', 'http'),
            timeout=endpoint_config.get('timeout', 30),
            skip_ssl_verify=endpoint_config.get('skip_ssl_verify', False),
            metadata=endpoint_config.get('metadata', {}),
        )
        endpoints.append(endpoint)
    
    return endpoints


def benchmark_single_server(
    url: str,
    name: Optional[str] = None,
    iterations: int = 10,
    output_dir: Optional[Path] = None,
) -> None:
    """Benchmark a single server."""
    if not name:
        name = url.split('/')[-1] or 'server'
    
    print(f"\nBenchmarking Single Server: {name}")
    print("=" * 60)
    
    endpoint = ServerEndpoint(name=name, url=url)
    runner = BatchBenchmarkRunner([endpoint])
    comparison = runner.run_benchmarks(iterations_per_method=iterations)
    
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate reports
        reporter = BenchmarkReportGenerator(comparison)
        reporter.generate_json_report(output_dir / f"{name}_benchmark.json")
        reporter.generate_csv_report(output_dir / f"{name}_benchmark.csv")
        reporter.generate_html_report(output_dir / f"{name}_benchmark.html")
        
        print(f"\n✓ Reports saved to: {output_dir}")


def benchmark_endpoints_from_config(
    config_file: Path,
    iterations: int = 10,
    output_dir: Optional[Path] = None,
    format: str = "all",
) -> None:
    """Benchmark multiple endpoints from configuration file."""
    print(f"\nLoading endpoints from: {config_file}")
    
    try:
        endpoints = load_endpoints_from_config(config_file)
    except FileNotFoundError:
        print(f"❌ Config file not found: {config_file}")
        return
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in config file: {e}")
        return
    
    if not endpoints:
        print("❌ No endpoints found in configuration")
        return
    
    print(f"✓ Loaded {len(endpoints)} endpoints")
    
    # Run benchmarks
    runner = BatchBenchmarkRunner(endpoints)
    comparison = runner.run_benchmarks(iterations_per_method=iterations)
    
    # Generate reports
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        reporter = BenchmarkReportGenerator(comparison)
        
        if format in ["all", "json"]:
            reporter.generate_json_report(output_dir / "benchmark_results.json")
        
        if format in ["all", "csv"]:
            reporter.generate_csv_report(output_dir / "benchmark_results.csv")
        
        if format in ["all", "html"]:
            reporter.generate_html_report(output_dir / "benchmark_results.html")
        
        print(f"\n✓ Reports saved to: {output_dir}")


def stress_test_endpoints(
    config_file: Path,
    method: str = "tools/list",
    duration: int = 30,
    initial_rps: int = 1,
    max_rps: int = 100,
    output_dir: Optional[Path] = None,
) -> None:
    """Stress test multiple endpoints from configuration."""
    print(f"\nLoading endpoints from: {config_file}")
    
    try:
        endpoints = load_endpoints_from_config(config_file)
    except FileNotFoundError:
        print(f"❌ Config file not found: {config_file}")
        return
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in config file: {e}")
        return
    
    if not endpoints:
        print("❌ No endpoints found in configuration")
        return
    
    print(f"✓ Loaded {len(endpoints)} endpoints")
    
    # Run stress tests
    runner = BatchBenchmarkRunner(endpoints)
    comparison = runner.run_stress_tests(
        method=method,
        duration_seconds=duration,
        initial_rps=initial_rps,
        max_rps=max_rps,
    )
    
    # Generate reports
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        reporter = BenchmarkReportGenerator(comparison)
        reporter.generate_json_report(output_dir / "stress_test_results.json")
        reporter.generate_csv_report(output_dir / "stress_test_results.csv")
        reporter.generate_html_report(output_dir / "stress_test_results.html")
        
        print(f"\n✓ Reports saved to: {output_dir}")


def list_endpoints(config_file: Path) -> None:
    """List all endpoints in configuration file."""
    try:
        endpoints = load_endpoints_from_config(config_file)
    except FileNotFoundError:
        print(f"❌ Config file not found: {config_file}")
        return
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in config file: {e}")
        return
    
    if not endpoints:
        print("No endpoints found")
        return
    
    print(f"\n📋 Endpoints in {config_file}:")
    print("=" * 80)
    for i, endpoint in enumerate(endpoints, 1):
        print(f"{i}. {endpoint.name}")
        print(f"   URL: {endpoint.url}")
        print(f"   Timeout: {endpoint.timeout}s")
        if endpoint.metadata:
            print(f"   Metadata: {endpoint.metadata}")
        print()


def generate_example_config(output_file: Path) -> None:
    """Generate example configuration file."""
    example_config = {
        "endpoints": [
            {
                "name": "Reference MCP Server",
                "url": "http://localhost:8000",
                "timeout": 30,
                "skip_ssl_verify": False,
                "metadata": {"version": "1.0", "type": "reference"}
            },
            {
                "name": "Non-Compliant Test Server",
                "url": "http://localhost:8001",
                "timeout": 30,
                "skip_ssl_verify": False,
                "metadata": {"version": "1.0", "type": "test"}
            },
            {
                "name": "External MCP Server",
                "url": "http://external.example.com:8000",
                "timeout": 30,
                "skip_ssl_verify": False,
                "metadata": {"version": "2.0", "type": "external"}
            }
        ]
    }
    
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(example_config, f, indent=2)
    
    print(f"✓ Example configuration created: {output_file}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Benchmark external MCP servers for performance comparison",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Benchmark single server
  python benchmark_external.py --url http://localhost:8000 --name my-server
  
  # Benchmark endpoints from config
  python benchmark_external.py --config config/endpoints.json --output reports/
  
  # Stress test servers
  python benchmark_external.py --config config/endpoints.json --stress-test --duration 60 --max-rps 1000
  
  # List endpoints in config
  python benchmark_external.py --config config/endpoints.json --list
  
  # Generate example config
  python benchmark_external.py --generate-config config/endpoints_example.json
        """
    )
    
    parser.add_argument('--url', help='URL of single server to benchmark')
    parser.add_argument('--name', help='Name for single server benchmark')
    parser.add_argument('--config', type=Path, help='Configuration file with endpoints')
    parser.add_argument('--output', type=Path, default=Path('benchmark_reports'),
                        help='Output directory for reports (default: benchmark_reports)')
    parser.add_argument('--iterations', type=int, default=10,
                        help='Iterations per method (default: 10)')
    parser.add_argument('--format', choices=['all', 'json', 'csv', 'html'], default='all',
                        help='Report format(s) to generate (default: all)')
    
    # Stress testing options
    parser.add_argument('--stress-test', action='store_true',
                        help='Run stress test instead of normal benchmark')
    parser.add_argument('--method', default='tools/list',
                        help='MCP method to stress test (default: tools/list)')
    parser.add_argument('--duration', type=int, default=30,
                        help='Stress test duration in seconds (default: 30)')
    parser.add_argument('--initial-rps', type=int, default=1,
                        help='Initial requests per second (default: 1)')
    parser.add_argument('--max-rps', type=int, default=100,
                        help='Maximum requests per second (default: 100)')
    
    # Other options
    parser.add_argument('--list', action='store_true',
                        help='List endpoints in configuration')
    parser.add_argument('--generate-config', type=Path,
                        help='Generate example configuration file')
    
    args = parser.parse_args()
    
    # Generate example config
    if args.generate_config:
        generate_example_config(args.generate_config)
        return
    
    # List endpoints
    if args.list:
        if not args.config:
            print("❌ --config is required for --list")
            return
        list_endpoints(args.config)
        return
    
    # Benchmark single server
    if args.url:
        benchmark_single_server(
            args.url,
            name=args.name,
            iterations=args.iterations,
            output_dir=args.output,
        )
        return
    
    # Benchmark from config
    if args.config:
        if not args.config.exists():
            print(f"❌ Config file not found: {args.config}")
            return
        
        if args.stress_test:
            stress_test_endpoints(
                args.config,
                method=args.method,
                duration=args.duration,
                initial_rps=args.initial_rps,
                max_rps=args.max_rps,
                output_dir=args.output,
            )
        else:
            benchmark_endpoints_from_config(
                args.config,
                iterations=args.iterations,
                output_dir=args.output,
                format=args.format,
            )
        return
    
    # No action specified
    print("❌ Please specify either --url, --config, --list, or --generate-config")
    parser.print_help()


if __name__ == '__main__':
    main()
