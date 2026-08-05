"""
Property-based conformance tests using Hypothesis.

Where the hand-written suite cases probe specific known inputs, these tests
generate large families of malformed and edge-case inputs automatically and
assert invariants that must hold for *every* generated input. They run against
the local compliant sample server, started once per session as a subprocess.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests
from hypothesis import given, settings
from hypothesis import strategies as st


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "http://127.0.0.1:8000"
REQUEST_TIMEOUT = 3


def _server_is_up(url):
    try:
        requests.post(
            url, json={"jsonrpc": "2.0", "method": "ping", "params": {}, "id": 1},
            timeout=1,
        )
        return True
    except requests.RequestException:
        return False


@pytest.fixture(scope="session")
def server():
    """Start the compliant sample server as a subprocess on port 8000, wait
    until it is ready, drive it into the OPERATIONAL lifecycle state, yield the
    base URL, and always terminate it afterwards.

    If a sample server is already running on port 8000 (e.g. started by another
    test module's session fixture), reuse it instead of starting a second one.
    """
    if _server_is_up(BASE_URL):
        yield BASE_URL
        return

    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "sample_server.app"],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        # 2. Poll until ready (max 10 seconds).
        deadline = time.time() + 10
        ready = False
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("sample server exited before becoming ready")
            try:
                requests.post(
                    BASE_URL,
                    json={"jsonrpc": "2.0", "method": "ping", "params": {}, "id": 1},
                    timeout=1,
                )
                ready = True
                break
            except requests.RequestException:
                time.sleep(0.3)
        if not ready:
            raise RuntimeError("sample server did not become ready within 10s")

        # 3. Run initialize (+ initialized) once to reach OPERATIONAL state.
        requests.post(
            BASE_URL,
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "property-tests", "version": "1.0"},
                },
                "id": 1,
            },
            timeout=REQUEST_TIMEOUT,
        )
        requests.post(
            BASE_URL,
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
            timeout=REQUEST_TIMEOUT,
        )

        # 4. Yield the base URL for the property tests.
        yield BASE_URL
    finally:
        # 5. Terminate the server.
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


# --------------------------------------------------------------------------- #
# TEST 1 — every well-formed request produces a valid JSON-RPC response
# --------------------------------------------------------------------------- #
@given(
    method=st.text(
        alphabet=st.characters(
            whitelist_categories=('Lu', 'Ll', 'Nd'),
            whitelist_characters='/_-.',
        ),
        min_size=1, max_size=50,
    ),
    req_id=st.one_of(
        st.integers(min_value=1, max_value=9999),
        st.text(min_size=1, max_size=20),
    ),
)
@settings(max_examples=50, deadline=5000)
def test_well_formed_request_always_returns_valid_jsonrpc(server, method, req_id):
    resp = requests.post(
        server,
        json={"jsonrpc": "2.0", "method": method, "params": {}, "id": req_id},
        timeout=REQUEST_TIMEOUT,
    )
    body = resp.json()
    assert isinstance(body, dict), f"response is not a JSON object: {body!r}"
    assert body.get("jsonrpc") == "2.0", f"missing/invalid jsonrpc: {body!r}"
    has_result = "result" in body
    has_error = "error" in body
    assert has_result != has_error, (
        f"response must contain exactly one of result/error: {body!r}"
    )
    assert body.get("id") == req_id, (
        f"response id {body.get('id')!r} does not match sent id {req_id!r}"
    )


# --------------------------------------------------------------------------- #
# TEST 2 — request id is always echoed correctly
# --------------------------------------------------------------------------- #
@given(
    req_id=st.one_of(
        st.integers(min_value=-999, max_value=9999),
        st.text(min_size=1, max_size=100),
    ),
)
@settings(max_examples=50, deadline=5000)
def test_request_id_always_echoed(server, req_id):
    resp = requests.post(
        server,
        json={
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
            "id": req_id,
        },
        timeout=REQUEST_TIMEOUT,
    )
    body = resp.json()
    assert body.get("jsonrpc") == "2.0", f"invalid envelope: {body!r}"
    assert body.get("id") == req_id, (
        f"response id {body.get('id')!r} does not match sent id {req_id!r}"
    )


# --------------------------------------------------------------------------- #
# TEST 3 — error codes are always in the valid JSON-RPC range
# --------------------------------------------------------------------------- #
def _is_valid_error_code(code):
    """Valid JSON-RPC error code: standard/reserved (-32768..-32000) or a
    server-defined application error (1..32767)."""
    if not isinstance(code, int) or isinstance(code, bool):
        return False
    return (-32768 <= code <= -32000) or (1 <= code <= 32767)


@given(
    method=st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Ll')),
        min_size=1, max_size=30,
    ).map(lambda s: "nonexistent_" + s),
)
@settings(max_examples=50, deadline=5000)
def test_error_codes_always_valid_range(server, method):
    resp = requests.post(
        server,
        json={"jsonrpc": "2.0", "method": method, "params": {}, "id": 1},
        timeout=REQUEST_TIMEOUT,
    )
    body = resp.json()
    assert "error" in body, f"expected an error for unknown method: {body!r}"
    error = body["error"]
    assert isinstance(error, dict), f"error must be an object: {error!r}"
    assert isinstance(error.get("code"), int) and not isinstance(
        error.get("code"), bool
    ), f"error code must be an integer: {error!r}"
    assert isinstance(error.get("message"), str) and error["message"], (
        f"error message must be a non-empty string: {error!r}"
    )
    assert _is_valid_error_code(error["code"]), (
        f"error code {error['code']} is outside valid JSON-RPC ranges"
    )


# --------------------------------------------------------------------------- #
# TEST 4 — server never crashes on arbitrary malformed input
# --------------------------------------------------------------------------- #
@given(
    body=st.one_of(
        st.text(min_size=0, max_size=200),
        st.just("null"),
        st.just("true"),
        st.just("[]"),
        st.just("[1,2,3]"),
        st.integers().map(str),
        st.fixed_dictionaries({
            "jsonrpc": st.text(min_size=0, max_size=10),
            "method": st.one_of(
                st.none(), st.integers(), st.text(min_size=0, max_size=20)
            ),
            "id": st.integers(),
        }).map(json.dumps),
    ),
)
@settings(max_examples=100, deadline=5000)
def test_server_never_crashes_on_malformed_input(server, body):
    try:
        resp = requests.post(
            server,
            data=body.encode("utf-8", errors="replace"),
            headers={"Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise AssertionError(
            f"server did not return an HTTP response (possible crash) for "
            f"body {body!r}: {exc}"
        )
    # Any HTTP status is acceptable; a 5xx signals a server crash/unhandled error.
    assert resp.status_code < 500, (
        f"server returned {resp.status_code} (server error) for body {body!r}"
    )


# --------------------------------------------------------------------------- #
# TEST 5 — tools/list response always has a consistent shape
# --------------------------------------------------------------------------- #
_tools_shape_seen = []


@given(req_id=st.integers(min_value=1, max_value=9999))
@settings(max_examples=20, deadline=5000)
def test_tools_list_always_consistent(server, req_id):
    resp = requests.post(
        server,
        json={"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": req_id},
        timeout=REQUEST_TIMEOUT,
    )
    body = resp.json()
    assert "result" in body, f"tools/list did not return a result: {body!r}"
    tools = body["result"].get("tools")
    assert isinstance(tools, list), f"tools must be a list: {body!r}"
    shape = (len(tools), tuple(sorted(t["name"] for t in tools)))
    if not _tools_shape_seen:
        _tools_shape_seen.append(shape)
    assert shape == _tools_shape_seen[0], (
        f"tools/list shape changed across calls: {shape} != {_tools_shape_seen[0]}"
    )
