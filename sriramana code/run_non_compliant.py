#!/usr/bin/env python
"""
CLI runner for the non-compliant MCP server with configurable violations.
Allows testing specific protocol violations against the assurance framework.
"""
import argparse
import sys
import subprocess
import time
import requests
from pathlib import Path


def start_server(violations=None, port=8001):
    """Start the non-compliant server with specified violations."""
    print(f"Starting non-compliant MCP server on http://127.0.0.1:{port}...")

    # Import to set violations before starting
    sys.path.insert(0, str(Path(__file__).parent))
    from sample_server.non_compliant import app, set_violation, reset_violations

    reset_violations()

    if violations:
        print(f"\nEnabling violations:")
        for violation in violations:
            set_violation(violation, True)
            print(f"  [OK] {violation}")

    print("\nServer starting...\n")
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


def list_violations():
    """List all available violations."""
    sys.path.insert(0, str(Path(__file__).parent))
    from sample_server.non_compliant import VIOLATIONS
    
    print("\nAvailable violations:\n")
    for i, violation_name in enumerate(sorted(VIOLATIONS.keys()), 1):
        print(f"{i:2}. {violation_name}")
    print()


def test_server_health():
    """Test if server is running and responsive."""
    try:
        response = requests.post(
            "http://127.0.0.1:8001/",
            json={"jsonrpc": "2.0", "method": "ping", "params": {}, "id": 1},
            timeout=2
        )
        return response.status_code == 200
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Run non-compliant MCP server with configurable violations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start with no violations (compliant baseline)
  python run_non_compliant.py

  # Start with specific violations
  python run_non_compliant.py --violations missing_jsonrpc invalid_jsonrpc_version

  # Test all violations one by one
  python run_non_compliant.py --list-violations
        """
    )
    
    parser.add_argument(
        "--violations",
        nargs="+",
        help="List of violations to enable"
    )
    
    parser.add_argument(
        "--list-violations",
        action="store_true",
        help="List all available violations and exit"
    )
    
    parser.add_argument(
        "--no-start",
        action="store_true",
        help="Don't start the server (useful for setup)"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8001,
        help="Port to run the non-compliant server on (default: 8001)"
    )

    args = parser.parse_args()
    
    if args.list_violations:
        list_violations()
        return 0
    
    if not args.no_start:
        try:
            start_server(violations=args.violations, port=args.port)
        except KeyboardInterrupt:
            print("\n\nServer stopped.")
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
