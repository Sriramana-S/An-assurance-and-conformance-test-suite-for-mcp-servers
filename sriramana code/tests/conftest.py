import os
import threading

import pytest
from werkzeug.serving import make_server

from core.client import MCPClient
from sample_server.app import app


PROTOCOL_VERSION = os.getenv("MCP_PROTOCOL_VERSION", "2025-11-25")


@pytest.fixture(scope="session")
def server_url():
    external_url = os.getenv("MCP_SERVER_URL")
    if external_url:
        yield external_url
        return

    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture
def protocol_version():
    return PROTOCOL_VERSION


@pytest.fixture
def client(server_url, protocol_version):
    return MCPClient(
        server_url,
        timeout=5,
        protocol_version=protocol_version,
    )
