#!/usr/bin/env python
"""
CLI runner for external MCP server testing and comparative analysis.
Supports batch testing of multiple endpoints with comprehensive reporting.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from core.batch_runner import BatchTestRunner
from core.comparison_reporter import ComparisonReportGenerator
from core.external_client import ServerEndpoint


def load_endpoints_config(config_file: Path) -> List[ServerEndpoint]:
    """
    Load endpoints from configuration file.

    Args:
        config_file: Path to endpoints.json

    Returns:
        List of ServerEndpoint objects
    """
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"Error: Config file not found: {config_file}")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in config file: {config_file}")
        sys.exit(1)

    endpoints = []
    for endpoint_config in config.get("endpoints", []):
        endpoint = ServerEndpoint(
            name=endpoint_config.get("name", "Unknown"),
            url=endpoint_config.get("url", ""),
            command=endpoint_config.get("command"),
            description=endpoint_config.get("description"),
            protocol=endpoint_config.get("protocol", "http"),
            timeout=endpoint_config.get("timeout", 30),
            skip_ssl_verify=endpoint_config.get("skip_ssl_verify", False),
            metadata=endpoint_config.get("metadata", {}),
        )
        endpoints.append(endpoint)

    return endpoints


def create_sample_config(output_file: Path) -> None:
    """
    Create sample endpoints configuration file.

    Args:
        output_file: Output file path
    """
    sample_config = {
        "endpoints": [
            {
                "name": "Local Compliant",
                "url": "http://127.0.0.1:8000",
                "description": "Local MCP server",
                "protocol": "http",
                "timeout": 30,
                "skip_ssl_verify": False,
                "metadata": {"type": "test"}
            }
        ],
        "testing_options": {
            "max_retries": 3,
            "timeout_seconds": 30,
            "skip_ssl_verification": False,
            "parallel_testing": False
        },
        "report_options": {
            "generate_json": True,
            "generate_html": True,
            "generate_csv": True,
            "include_metrics": True,
            "include_failure_analysis": True
        }
    }

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(sample_config, f, indent=2)

    print(f"Created sample config: {output_file}")


def test_single_endpoint(
    url: str,
    name: Optional[str] = None,
    output_dir: Path = Path("reports/external"),
) -> None:
    """
    Test a single external endpoint.

    Args:
        url: Server URL
        name: Endpoint name (defaults to URL)
        output_dir: Output directory for reports
    """
    endpoint = ServerEndpoint(
        name=name or url,
        url=url,
        description=f"External server at {url}",
    )

    runner = BatchTestRunner([endpoint])
    results = runner.run_batch()

    # Generate reports
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    runner.save_results_json(output_dir / "batch_results.json")
    runner.save_individual_results(output_dir / "individual_results")

    # Generate comparison reports
    reporter = ComparisonReportGenerator(results)
    reporter.generate_json_report(output_dir / "comparison_report.json")
    reporter.generate_csv_report(output_dir / "comparison_report.csv")
    reporter.generate_html_report(output_dir / "comparison_report.html")

    print(f"\nReports generated in: {output_dir}")


def test_endpoints_from_config(
    config_file: Path,
    output_dir: Path = Path("reports/comparative"),
) -> None:
    """
    Test multiple endpoints from configuration.

    Args:
        config_file: Path to endpoints.json
        output_dir: Output directory for reports
    """
    print(f"Loading endpoints from: {config_file}")
    endpoints = load_endpoints_config(config_file)

    if not endpoints:
        print("No endpoints found in configuration")
        return

    print(f"Found {len(endpoints)} endpoints to test\n")

    # Run batch tests
    runner = BatchTestRunner(endpoints)
    results = runner.run_batch()

    # Generate reports
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    runner.save_results_json(output_dir / "batch_results.json")
    runner.save_individual_results(output_dir / "individual_results")

    # Generate comparison reports
    reporter = ComparisonReportGenerator(results)
    reporter.generate_json_report(output_dir / "comparison_report.json")
    reporter.generate_csv_report(output_dir / "comparison_report.csv")
    reporter.generate_html_report(output_dir / "comparison_report.html")

    print(f"\n✓ Batch testing complete!")
    print(f"✓ Reports generated in: {output_dir}")
    print(f"\nComparison Reports:")
    print(f"  - HTML:  {output_dir / 'comparison_report.html'}")
    print(f"  - JSON:  {output_dir / 'comparison_report.json'}")
    print(f"  - CSV:   {output_dir / 'comparison_report.csv'}")


def main():
    parser = argparse.ArgumentParser(
        description="Test external MCP servers and generate comparative reports",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test single external server
  python test_external.py --endpoint http://example.com/mcp --name "Example Server"

  # Test multiple servers from config
  python test_external.py --config config/endpoints_example.json

  # Create sample config
  python test_external.py --create-sample-config config/my_endpoints.json
        """
    )

    parser.add_argument(
        "--endpoint",
        help="Test single external endpoint URL"
    )

    parser.add_argument(
        "--endpoint-name",
        help="Name for single endpoint (defaults to URL)"
    )

    parser.add_argument(
        "--config",
        type=Path,
        help="Test multiple endpoints from config file"
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/external"),
        help="Output directory for reports"
    )

    parser.add_argument(
        "--create-sample-config",
        type=Path,
        help="Create sample endpoints configuration file"
    )

    parser.add_argument(
        "--list-endpoints",
        action="store_true",
        help="List endpoints from config file"
    )

    args = parser.parse_args()

    # Create sample config
    if args.create_sample_config:
        create_sample_config(args.create_sample_config)
        return

    # List endpoints
    if args.list_endpoints and args.config:
        endpoints = load_endpoints_config(args.config)
        print(f"\nEndpoints in {args.config}:\n")
        for i, endpoint in enumerate(endpoints, 1):
            print(f"{i}. {endpoint.name}")
            print(f"   URL: {endpoint.url}")
            if endpoint.description:
                print(f"   Description: {endpoint.description}")
            print()
        return

    # Test single endpoint
    if args.endpoint:
        print(f"Testing endpoint: {args.endpoint}\n")
        test_single_endpoint(
            args.endpoint,
            args.endpoint_name,
            args.output_dir
        )
        return

    # Test multiple endpoints from config
    if args.config:
        test_endpoints_from_config(args.config, args.output_dir)
        return

    # No action specified
    parser.print_help()


if __name__ == "__main__":
    main()
