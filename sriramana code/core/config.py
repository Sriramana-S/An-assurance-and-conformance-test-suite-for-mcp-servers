import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SuiteConfig:
    transport: str = "http"
    server_url: str = "http://127.0.0.1:8000"
    command: str | None = None
    protocol_version: str = "2025-11-25"
    output_dir: str = "reports/local_sample"
    request_timeout: float = 5.0
    use_sample_server: bool = True

    @classmethod
    def from_file(cls, path: str | None = None) -> "SuiteConfig":
        config = cls()
        config_path = Path(path or "config/default.json")

        if config_path.exists():
            with config_path.open("r", encoding="utf-8") as file:
                data: dict[str, Any] = json.load(file)
            config = cls(
                transport=data.get("transport", config.transport),
                server_url=data.get("server_url", config.server_url),
                command=data.get("command", config.command),
                protocol_version=data.get(
                    "protocol_version",
                    config.protocol_version,
                ),
                output_dir=data.get("output_dir", config.output_dir),
                request_timeout=float(
                    data.get("request_timeout", config.request_timeout)
                ),
                use_sample_server=bool(
                    data.get("use_sample_server", config.use_sample_server)
                ),
            )

        if os.getenv("MCP_TRANSPORT"):
            config.transport = os.environ["MCP_TRANSPORT"]
        if os.getenv("MCP_SERVER_URL"):
            config.server_url = os.environ["MCP_SERVER_URL"]
            config.use_sample_server = False
        if os.getenv("MCP_COMMAND"):
            config.command = os.environ["MCP_COMMAND"]
            config.transport = "stdio"
            config.use_sample_server = False
        if os.getenv("MCP_PROTOCOL_VERSION"):
            config.protocol_version = os.environ["MCP_PROTOCOL_VERSION"]
        if os.getenv("MCP_REPORT_DIR"):
            config.output_dir = os.environ["MCP_REPORT_DIR"]
        if os.getenv("MCP_REQUEST_TIMEOUT"):
            config.request_timeout = float(os.environ["MCP_REQUEST_TIMEOUT"])

        return config
