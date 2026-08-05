"""
Tests for non-compliant MCP server violation detection.

Each test starts the non-compliant server on a dedicated port (8099) with one
specific violation enabled, runs the assurance suite against it, and asserts
that the *relevant* assurance case is actually scored FAIL (a wrong response on
a MUST case) or WARN (a silent drop). This verifies the framework detects each
violation behaviourally — not merely that some object is the right type.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

from core.client import HttpMCPClient
from core.suite import run_suite


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUN_SCRIPT = str(PROJECT_ROOT / "run_non_compliant.py")
PORT = 8099
BASE_URL = f"http://127.0.0.1:{PORT}"
PROTOCOL_VERSION = "2025-11-25"


def _wait_until_ready(proc, attempts=30):
    """Poll the server until it answers an HTTP request, failing fast if the
    process exits before becoming reachable."""
    for _ in range(attempts):
        if proc.poll() is not None:
            raise RuntimeError(
                "non-compliant server exited before it was ready "
                f"(exit code {proc.returncode})"
            )
        try:
            requests.post(
                f"{BASE_URL}/",
                json={"jsonrpc": "2.0", "method": "ping", "params": {}, "id": 1},
                timeout=1,
            )
            return
        except requests.RequestException:
            time.sleep(0.5)
    raise RuntimeError("non-compliant server did not become ready in time")


def _results_for_violation(violation_flag):
    """Start the non-compliant server with exactly one violation enabled on a
    dedicated port, run the full assurance suite against it, and return the
    list of AssuranceResult objects. The server is always stopped afterwards."""
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen(
        [
            sys.executable,
            RUN_SCRIPT,
            "--violations", violation_flag,
            "--port", str(PORT),
        ],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        _wait_until_ready(proc)
        client = HttpMCPClient(
            BASE_URL,
            timeout=5,
            protocol_version=PROTOCOL_VERSION,
        )
        return run_suite(client, PROTOCOL_VERSION)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _assert_case_flagged(violation_flag, case_name):
    """Assert that, with `violation_flag` enabled, the assurance case named
    `case_name` is detected as FAIL (wrong response) or WARN (silent drop)."""
    results = _results_for_violation(violation_flag)
    target = next((r for r in results if r.test == case_name), None)
    assert target is not None, (
        f"Assurance case {case_name!r} was not found in the suite results "
        f"for violation {violation_flag!r}"
    )
    assert target.status in ("FAIL", "WARN"), (
        f"Expected case {case_name!r} to be FAIL or WARN under violation "
        f"{violation_flag!r}, but got {target.status}: {target.message}"
    )


# --- JSON-RPC envelope violations ------------------------------------------ #

def test_missing_jsonrpc_field_detected():
    """A response omitting the jsonrpc field must fail the handshake."""
    _assert_case_flagged("missing_jsonrpc", "Initialize Handshake")


def test_invalid_jsonrpc_version_detected():
    """A response with jsonrpc != '2.0' must fail the handshake."""
    _assert_case_flagged("invalid_jsonrpc_version", "Initialize Handshake")


# --- MCP initialize / capability violations -------------------------------- #

def test_invalid_initialize_response_structure_detected():
    """An initialize result missing required fields must fail the handshake."""
    _assert_case_flagged("invalid_initialize_response", "Initialize Handshake")


def test_missing_server_info_name_detected():
    """An empty serverInfo.name must fail the handshake."""
    _assert_case_flagged("missing_server_name", "Initialize Handshake")


def test_invalid_tools_list_detected():
    """A malformed tools/list response must fail the tools list schema case."""
    _assert_case_flagged("invalid_tools_list", "Tools List Schema")


def test_invalid_resources_list_detected():
    """A malformed resources/list response must fail the resources list case."""
    _assert_case_flagged("invalid_resources_list", "Resources List Schema")


def test_invalid_resources_read_detected():
    """A malformed resources/read response must fail the resource read case."""
    _assert_case_flagged("invalid_resources_read", "Resource Read Validation")


def test_invalid_prompts_get_detected():
    """A malformed prompts/get response must fail the prompt get case."""
    _assert_case_flagged("invalid_prompts_get", "Prompt Get Validation")


# --- Error-object violations ----------------------------------------------- #

def test_invalid_error_object_detected():
    """A non-object error field must fail the unknown-method rejection case."""
    _assert_case_flagged("invalid_error_object", "Unknown Method Rejection")
