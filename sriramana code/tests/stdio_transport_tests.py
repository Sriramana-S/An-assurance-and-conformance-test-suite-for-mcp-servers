import os
import sys
import tempfile

from core.client import StdioMCPClient
from core.suite import run_initialize_test, run_suite


def stdio_command():
    return f'"{sys.executable}" -m sample_server.stdio_app'


def test_stdio_client_runs_initialize(protocol_version):
    client = StdioMCPClient(stdio_command(), timeout=5)
    try:
        result = run_initialize_test(client, protocol_version)
    finally:
        client.close()

    assert result.status == "PASS", result.message
    assert client.get_metrics().transport_type == "stdio"
    assert client.get_metrics().request_count >= 1


def test_stdio_client_runs_full_assurance_suite(protocol_version):
    client = StdioMCPClient(stdio_command(), timeout=5)
    try:
        results = run_suite(client, protocol_version)
    finally:
        client.close()

    failures = [result for result in results if result.status == "FAIL"]
    assert not failures, [failure.message for failure in failures]


def test_stdio_client_waits_for_matching_response_id():
    server_source = """
import json
import sys


def write(message):
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\\n")
    sys.stdout.flush()


write({
    "jsonrpc": "2.0",
    "method": "notifications/progress",
    "params": {"message": "startup"},
})

for line in sys.stdin:
    request = json.loads(line)
    write({
        "jsonrpc": "2.0",
        "id": request.get("id"),
        "result": {"ok": True},
    })
"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(server_source)
        server_script = handle.name

    try:
        client = StdioMCPClient([sys.executable, server_script], timeout=5)
        try:
            response = client.send_payload(
                {
                    "jsonrpc": "2.0",
                    "method": "ping",
                    "id": "expected-id",
                }
            )
        finally:
            client.close()

        assert not response.has_transport_error
        assert response.status_code == 200
        assert response.body["id"] == "expected-id"
        assert response.body["result"] == {"ok": True}
    finally:
        os.remove(server_script)
