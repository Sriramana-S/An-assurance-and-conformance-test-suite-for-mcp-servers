"""
Extended MCP client for testing external MCP servers.
Supports endpoint metadata, retry logic, and performance tracking.
"""
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from core.client import HttpMCPClient, StdioMCPClient
from core.models import ClientResponse

# Default MCP protocol version negotiated with external servers. Mirrors the
# value HttpMCPClient sends via the MCP-Protocol-Version header in core/client.py.
DEFAULT_PROTOCOL_VERSION = "2025-11-25"


@dataclass
class ServerEndpoint:
    """Represents an external MCP server endpoint."""
    name: str
    url: str
    command: Optional[str] = None
    description: Optional[str] = None
    protocol: str = "http"
    timeout: int = 30
    skip_ssl_verify: bool = False
    metadata: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.name} ({self.url})"

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "name": self.name,
            "url": self.url,
            "command": self.command,
            "description": self.description,
            "protocol": self.protocol,
            "timeout": self.timeout,
            "skip_ssl_verify": self.skip_ssl_verify,
            "metadata": self.metadata,
        }


@dataclass
class PerformanceMetrics:
    """Performance metrics for a server interaction."""
    transport_type: str = "http"
    request_count: int = 0
    response_time_min: float = float('inf')
    response_time_max: float = 0.0
    response_time_total: float = 0.0
    error_count: int = 0
    success_count: int = 0
    last_request_time: Optional[datetime] = None

    def average_response_time(self) -> float:
        """Calculate average response time."""
        if self.request_count == 0:
            return 0.0
        return self.response_time_total / self.request_count

    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.request_count == 0:
            return 0.0
        return (self.success_count / self.request_count) * 100

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "request_count": self.request_count,
            "transport_type": self.transport_type,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "average_response_time_ms": round(self.average_response_time() * 1000, 2),
            "min_response_time_ms": round(self.response_time_min * 1000, 2) if self.response_time_min != float('inf') else 0,
            "max_response_time_ms": round(self.response_time_max * 1000, 2),
            "success_rate": round(self.success_rate(), 2),
        }


class ExternalMCPClient:
    """Extended MCP client for external server testing."""

    def __init__(self, endpoint: ServerEndpoint, max_retries: int = 3):
        """
        Initialize client for external endpoint.

        Args:
            endpoint: ServerEndpoint configuration
            max_retries: Maximum retry attempts on failure
        """
        self.endpoint = endpoint
        self.max_retries = max_retries
        self.client = self._create_client(endpoint)
        self.metrics = PerformanceMetrics(transport_type=endpoint.protocol)
        self.start_time = datetime.now()

    def send_request(
        self,
        method: str,
        params: dict = None,
        request_id: int = None,
        retry: bool = True,
    ) -> ClientResponse:
        """
        Send request with retry logic and performance tracking.

        Args:
            method: MCP method name
            params: Request parameters
            request_id: Request ID
            retry: Enable retry on failure

        Returns:
            ClientResponse with performance metrics attached
        """
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": request_id,
        }

        attempt = 0
        last_error = None

        while attempt < self.max_retries:
            try:
                start = time.time()
                response = self.client.send_payload(payload)
                elapsed = time.time() - start

                # Track metrics
                self.metrics.request_count += 1
                self.metrics.response_time_total += elapsed
                self.metrics.response_time_min = min(self.metrics.response_time_min, elapsed)
                self.metrics.response_time_max = max(self.metrics.response_time_max, elapsed)
                self.metrics.last_request_time = datetime.now()

                if response.has_transport_error:
                    self.metrics.error_count += 1
                    if retry and attempt < self.max_retries - 1:
                        attempt += 1
                        continue
                else:
                    self.metrics.success_count += 1

                return response

            except Exception as e:
                last_error = e
                self.metrics.error_count += 1
                if retry and attempt < self.max_retries - 1:
                    attempt += 1
                    time.sleep(0.5 * (attempt + 1))  # Exponential backoff
                else:
                    break

        # Return error response after all retries exhausted
        self.metrics.request_count += 1
        return ClientResponse(
            body=None,
            status_code=0,
            transport_error=str(last_error or "Max retries exceeded"),
        )

    def close(self) -> None:
        """Close underlying transport client."""
        self.client.close()

    def get_metrics(self) -> PerformanceMetrics:
        """Get performance metrics."""
        return self.metrics

    def get_session_duration(self) -> float:
        """Get session duration in seconds."""
        return (datetime.now() - self.start_time).total_seconds()

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "endpoint": self.endpoint.to_dict(),
            "metrics": self.metrics.to_dict(),
            "transport_metrics": self.client.get_metrics().to_dict(),
            "session_duration_seconds": round(self.get_session_duration(), 2),
        }

    @staticmethod
    def _create_client(endpoint: ServerEndpoint):
        # Allow the protocol version to be configured per-endpoint via metadata,
        # otherwise fall back to the suite default so the server always receives
        # the MCP-Protocol-Version header.
        protocol_version = endpoint.metadata.get(
            "protocol_version",
            DEFAULT_PROTOCOL_VERSION,
        )

        if endpoint.protocol == "stdio":
            if not endpoint.command:
                raise ValueError("STDIO endpoint requires a command")
            return StdioMCPClient(
                endpoint.command,
                timeout=endpoint.timeout,
                protocol_version=protocol_version,
            )

        return HttpMCPClient(
            endpoint.url,
            timeout=endpoint.timeout,
            protocol_version=protocol_version,
        )
