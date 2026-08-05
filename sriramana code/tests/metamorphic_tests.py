"""
Metamorphic tests for the MCP conformance suite.

Metamorphic relations are implementation-independent properties that must hold
for *any* correct server: reordering independent requests must not change their
results, repeated reads must be consistent, reads must be idempotent, and
re-initialisation must be stable. They run against the local compliant sample
server (started once per session on port 8000, the same pattern as
property_tests.py).
"""
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
    """Start the compliant sample server on port 8000, drive it OPERATIONAL,
    yield the base URL, and terminate it. Reuses an already-running server on
    8000 (e.g. one started by property_tests' session fixture)."""
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
        deadline = time.time() + 10
        ready = False
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("sample server exited before becoming ready")
            if _server_is_up(BASE_URL):
                ready = True
                break
            time.sleep(0.3)
        if not ready:
            raise RuntimeError("sample server did not become ready within 10s")

        _post(BASE_URL, {
            "jsonrpc": "2.0", "method": "initialize", "id": 1,
            "params": {
                "protocolVersion": "2025-11-25", "capabilities": {},
                "clientInfo": {"name": "metamorphic-tests", "version": "1.0"},
            },
        })
        _notify(BASE_URL, {
            "jsonrpc": "2.0", "method": "notifications/initialized", "params": {},
        })
        yield BASE_URL
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _post(server, payload):
    return requests.post(server, json=payload, timeout=REQUEST_TIMEOUT).json()


def _notify(server, payload):
    """Send a notification (no id) - the server returns an empty 202 body, so
    do not attempt to parse JSON."""
    requests.post(server, json=payload, timeout=REQUEST_TIMEOUT)


# Maps a list method to the function that extracts its sorted identifiers.
_EXTRACT = {
    "tools/list": lambda body: tuple(sorted(t["name"] for t in body["result"]["tools"])),
    "resources/list": lambda body: tuple(sorted(r["uri"] for r in body["result"]["resources"])),
    "prompts/list": lambda body: tuple(sorted(p["name"] for p in body["result"]["prompts"])),
}

_LIST_METHODS = ["tools/list", "resources/list", "prompts/list"]


def _list_identifiers(server, method, req_id):
    body = _post(server, {"jsonrpc": "2.0", "id": req_id, "method": method,
                          "params": {}})
    return _EXTRACT[method](body)


# --------------------------------------------------------------------------- #
# MT1 - Reordering independent requests yields the same results
# --------------------------------------------------------------------------- #
_mt1_canonical = {}


@given(order=st.permutations(_LIST_METHODS))
@settings(max_examples=20, deadline=5000)
def test_mt1_reordering_independent_requests(server, order):
    observed = {}
    for i, method in enumerate(order):
        observed[method] = _list_identifiers(server, method, f"mt1-{i}")
    # Capture the canonical result the first time, then require every ordering
    # to produce identical identifiers for each list method.
    for method, ids in observed.items():
        baseline = _mt1_canonical.setdefault(method, ids)
        assert ids == baseline, (
            f"{method} returned different identifiers depending on request "
            f"order: {ids} != {baseline}"
        )


# --------------------------------------------------------------------------- #
# MT2 - Repeated list calls are consistent
# --------------------------------------------------------------------------- #
def test_mt2_repeated_list_calls_consistent(server):
    results = [
        _list_identifiers(server, "tools/list", f"mt2-{i}") for i in range(3)
    ]
    assert results[0] == results[1] == results[2], (
        f"tools/list was not deterministic across 3 calls: {results}"
    )
    assert len(results[0]) == len(set(results[0]))  # no duplicate names


# --------------------------------------------------------------------------- #
# MT3 - Reads are idempotent
# --------------------------------------------------------------------------- #
def test_mt3_reads_idempotent(server):
    listing = _post(server, {"jsonrpc": "2.0", "id": "mt3-list",
                             "method": "resources/list", "params": {}})
    resources = listing.get("result", {}).get("resources", [])
    if not resources:
        pytest.skip("server advertises no resources to read")

    uri = resources[0]["uri"]
    read1 = _post(server, {"jsonrpc": "2.0", "id": "mt3-r1",
                           "method": "resources/read", "params": {"uri": uri}})
    read2 = _post(server, {"jsonrpc": "2.0", "id": "mt3-r2",
                           "method": "resources/read", "params": {"uri": uri}})
    assert read1["result"]["contents"] == read2["result"]["contents"], (
        f"resources/read on {uri} was not idempotent"
    )


# --------------------------------------------------------------------------- #
# MT4 - Initialize / re-initialize stability
# --------------------------------------------------------------------------- #
def test_mt4_initialize_reinitialize_stable(server):
    init_payload = {
        "jsonrpc": "2.0", "method": "initialize", "id": "mt4-1",
        "params": {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "metamorphic", "version": "1.0"},
        },
    }
    first = _post(server, init_payload)["result"]
    _notify(server, {"jsonrpc": "2.0", "method": "notifications/initialized",
                     "params": {}})
    init_payload["id"] = "mt4-2"
    second = _post(server, init_payload)["result"]

    assert first["protocolVersion"] == second["protocolVersion"], (
        "protocolVersion changed across re-initialize"
    )
    assert first["serverInfo"]["name"] == second["serverInfo"]["name"], (
        "serverInfo.name changed across re-initialize"
    )
    assert set(first["capabilities"].keys()) == set(second["capabilities"].keys()), (
        "capabilities shape changed across re-initialize"
    )
