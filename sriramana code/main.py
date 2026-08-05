import argparse
import logging
import socket
import threading
from pathlib import Path
from urllib.parse import urlparse

from werkzeug.serving import make_server

from core.client import HttpMCPClient, StdioMCPClient
from core.config import SuiteConfig
from core.reporter import ReportGenerator
from core.suite import run_suite
from core.unified_reporter import RecommendationEngine
from sample_server.app import app
from sarif_reporter import SARIFReporter


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run MCP assurance and conformance checks."
    )
    parser.add_argument(
        "--config",
        default="config/default.json",
        help="Path to a JSON configuration file.",
    )
    parser.add_argument(
        "--transport",
        choices=["http", "stdio"],
        help="MCP transport to use.",
    )
    parser.add_argument(
        "--server-url",
        help="MCP server HTTP endpoint to test.",
    )
    parser.add_argument(
        "--command",
        help="STDIO server command, e.g. \"docker run -i mcp/time\".",
    )
    parser.add_argument(
        "--protocol-version",
        help="MCP protocol version to negotiate.",
    )
    parser.add_argument(
        "--output-dir",
        help="Directory where reports should be written.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        help="Request timeout in seconds.",
    )
    parser.add_argument(
        "--use-sample-server",
        action="store_true",
        help="Start the bundled local sample MCP server before testing.",
    )
    parser.add_argument(
        "--no-sample-server",
        action="store_true",
        help="Do not auto-start the sample server. Use this with --server-url.",
    )
    return parser.parse_args()


def host_port_from_url(url):
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


def is_port_open(host, port, timeout=0.5):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class SampleServer:
    def __init__(self, host="127.0.0.1", port=8000):
        self.server = make_server(host, port, app)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )

    def __enter__(self):
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.server.shutdown()
        self.thread.join(timeout=5)


def apply_cli_overrides(config, args):
    if args.transport:
        config.transport = args.transport
        if args.transport == "stdio":
            config.use_sample_server = False
            if not args.output_dir and config.output_dir == "reports/local_sample":
                config.output_dir = "reports/stdio_target"
    if args.server_url:
        config.server_url = args.server_url
        config.transport = "http"
        config.use_sample_server = False
        if not args.output_dir and config.output_dir == "reports/local_sample":
            config.output_dir = "reports/external_target"
    if args.command:
        config.command = args.command
        config.transport = "stdio"
        config.use_sample_server = False
        if not args.output_dir and config.output_dir == "reports/local_sample":
            config.output_dir = "reports/stdio_target"
    if args.protocol_version:
        config.protocol_version = args.protocol_version
    if args.output_dir:
        config.output_dir = args.output_dir
    if args.timeout is not None:
        config.request_timeout = args.timeout
    if args.use_sample_server:
        config.use_sample_server = True
    if args.no_sample_server:
        config.use_sample_server = False
    return config


def create_client(config):
    if config.transport == "http":
        return HttpMCPClient(
            config.server_url,
            timeout=config.request_timeout,
            protocol_version=config.protocol_version,
        )

    if config.transport == "stdio":
        if not config.command:
            raise SystemExit(
                "STDIO transport requires --command or MCP_COMMAND. "
                "Example: python main.py --transport stdio --command "
                "\"docker run -i mcp/time\""
            )
        return StdioMCPClient(
            config.command,
            timeout=config.request_timeout,
            protocol_version=config.protocol_version,
            # Give process cold-start (npx/uvx) a generous first-response budget
            # while keeping per-request waits short for ignored negative tests.
            startup_timeout=max(config.request_timeout, 30),
        )

    raise SystemExit(f"Unsupported transport: {config.transport}")


def run(config):
    if (
        config.transport == "http"
        and not config.use_sample_server
        and not config.server_url
    ):
        raise SystemExit(
            "No MCP server target configured. Set MCP_SERVER_URL or pass "
            "--server-url, or run local evaluation with --use-sample-server."
        )

    print("\nStarting MCP Assurance Suite...\n")
    print(f"Transport: {config.transport}")
    print(
        "Target: "
        f"{config.server_url if config.transport == 'http' else config.command}"
    )
    print(f"Protocol version: {config.protocol_version}\n")

    client = create_client(config)
    try:
        results = run_suite(client, config.protocol_version)
        transport_metrics = client.get_metrics().to_dict()
    finally:
        client.close()

    report = ReportGenerator(
        output_dir=config.output_dir,
        target_url=config.server_url if config.transport == "http" else config.command,
        protocol_version=config.protocol_version,
        transport_type=config.transport,
        transport_metrics=transport_metrics,
    )
    for result in results:
        report.add_result(result)

    # Severity-ranked, spec-cited remediation items (MUST violations first).
    report.recommendations = (
        RecommendationEngine.generate_spec_cited_recommendations(results)
    )

    report.print_report()
    report.save_json_report()
    report.save_html_report()

    # Also emit a SARIF 2.1.0 log so findings can surface as GitHub code-
    # scanning alerts.
    target_name = (
        config.server_url if config.transport == "http" else config.command
    )
    sarif_path = Path(config.output_dir) / "compliance_report.sarif"
    SARIFReporter().export(results, target_name or "mcp-target", str(sarif_path))
    print(f"SARIF report saved: {sarif_path}")

    return report.summary()


def main():
    args = parse_args()
    config = apply_cli_overrides(SuiteConfig.from_file(args.config), args)

    if config.transport == "http" and config.use_sample_server:
        host, port = host_port_from_url(config.server_url)
        if is_port_open(host, port):
            print(
                f"Sample server already reachable at {config.server_url}; "
                "using existing process."
            )
            return run(config)

        with SampleServer(host=host, port=port):
            return run(config)

    return run(config)


if __name__ == "__main__":
    main()
