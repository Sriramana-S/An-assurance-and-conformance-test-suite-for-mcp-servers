import json
import os
import queue
import shlex
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from typing import Any

import requests

from core.models import ClientResponse, TransportMetrics


class BaseMCPClient(ABC):
    """Abstract MCP client shared by HTTP and STDIO transports."""

    transport_type = "base"

    def __init__(self, timeout=5, protocol_version=None):
        self.timeout = timeout
        self.protocol_version = protocol_version
        self._next_id = 1
        self.metrics = TransportMetrics(self.transport_type)

    def send_request(self, method, params=None, request_id=None):
        if request_id is None:
            request_id = self._next_request_id()

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": request_id,
        }

        return self.send_payload(payload)

    def send_notification(self, method, params=None):
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }

        return self.send_payload(payload)

    @abstractmethod
    def send_payload(self, payload):
        raise NotImplementedError

    @abstractmethod
    def send_raw(self, raw_body):
        raise NotImplementedError

    def get_metrics(self) -> TransportMetrics:
        return self.metrics

    def close(self):
        """Release transport resources."""

    def _next_request_id(self):
        request_id = self._next_id
        self._next_id += 1
        return request_id

    def _record_response(self, response: ClientResponse, elapsed_ms: float):
        response.response_time_ms = elapsed_ms
        response.transport_type = self.transport_type
        self.metrics.record(response, elapsed_ms)
        return response

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


class HttpMCPClient(BaseMCPClient):
    """HTTP JSON-RPC MCP client."""

    transport_type = "http"

    def __init__(self, server_url, timeout=5, protocol_version=None):
        super().__init__(timeout=timeout, protocol_version=protocol_version)
        self.server_url = server_url

    def send_payload(self, payload):
        headers = self._headers()
        start = time.perf_counter()

        try:
            response = requests.post(
                self.server_url,
                json=payload,
                timeout=self.timeout,
                headers=headers,
            )
            result = self._to_client_response(response)
        except Exception as e:
            result = ClientResponse(
                status_code=None,
                transport_error=str(e),
            )

        elapsed_ms = (time.perf_counter() - start) * 1000
        return self._record_response(result, elapsed_ms)

    def send_raw(self, raw_body):
        headers = self._headers()
        start = time.perf_counter()

        try:
            response = requests.post(
                self.server_url,
                data=raw_body,
                timeout=self.timeout,
                headers=headers,
            )
            result = self._to_client_response(response)
        except Exception as e:
            result = ClientResponse(
                status_code=None,
                transport_error=str(e),
            )

        elapsed_ms = (time.perf_counter() - start) * 1000
        return self._record_response(result, elapsed_ms)

    def _headers(self):
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        if self.protocol_version:
            headers["MCP-Protocol-Version"] = self.protocol_version

        return headers

    def _to_client_response(self, response):
        text = response.text or ""
        body = None

        if text.strip():
            try:
                body = response.json()
            except ValueError:
                return ClientResponse(
                    status_code=response.status_code,
                    text=text,
                    transport_error="Response body is not valid JSON",
                )

        return ClientResponse(
            status_code=response.status_code,
            body=body,
            text=text,
        )


class StdioMCPClient(BaseMCPClient):
    """STDIO JSON-RPC MCP client using subprocess.Popen."""

    transport_type = "stdio"

    def __init__(
        self,
        command,
        timeout=5,
        protocol_version=None,
        cwd=None,
        env=None,
        startup_timeout=None,
    ):
        super().__init__(timeout=timeout, protocol_version=protocol_version)
        self.command = command
        self.cwd = cwd
        self.env = env
        # A longer budget for the server's *first* response absorbs process
        # cold-start (npx/uvx). Once the server has answered once it is up, so
        # every later request uses the short `timeout` - which lets negative
        # tests a server ignores fail fast instead of stalling on cold-start
        # padding. Defaults to `timeout` for backward compatibility.
        self.startup_timeout = (
            startup_timeout if startup_timeout is not None else timeout
        )
        self._first_response_seen = False
        self.process = None
        self._stdout_queue: queue.Queue[str] = queue.Queue()
        self._stderr_lines: list[str] = []
        self._stdout_thread = None
        self._stderr_thread = None
        self._lock = threading.Lock()
        self._start_process()

    def send_payload(self, payload):
        raw = json.dumps(payload, separators=(",", ":"))
        if "id" not in payload and self._is_notification(payload):
            return self._send_notification_raw(raw)
        return self._send_raw_and_wait(
            raw,
            expected_id=payload.get("id"),
            match_response_id="id" in payload,
        )

    def send_raw(self, raw_body):
        expected_id, match_response_id = self._request_id_from_raw(raw_body)
        return self._send_raw_and_wait(
            raw_body,
            expected_id=expected_id,
            match_response_id=match_response_id,
        )

    def close(self):
        if self.process is None:
            return

        if self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
            except Exception:
                pass

        self.process = None

    def _start_process(self):
        args = self._command_args(self.command)
        self.process = subprocess.Popen(
            args,
            cwd=self.cwd,
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=isinstance(args, str),
        )

        self._stdout_thread = threading.Thread(
            target=self._read_stdout,
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr,
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _send_notification_raw(self, raw_body):
        start = time.perf_counter()
        with self._lock:
            error = self._write_line(raw_body)

        if error:
            result = ClientResponse(status_code=None, transport_error=error)
        else:
            result = ClientResponse(status_code=202, body=None, text="")

        elapsed_ms = (time.perf_counter() - start) * 1000
        return self._record_response(result, elapsed_ms)

    def _send_raw_and_wait(
        self,
        raw_body,
        expected_id=None,
        match_response_id=False,
    ):
        start = time.perf_counter()

        with self._lock:
            error = self._write_line(raw_body)
            if error:
                result = ClientResponse(status_code=None, transport_error=error)
                elapsed_ms = (time.perf_counter() - start) * 1000
                return self._record_response(result, elapsed_ms)

            result = self._wait_for_response(expected_id, match_response_id)

        elapsed_ms = (time.perf_counter() - start) * 1000
        return self._record_response(result, elapsed_ms)

    def _wait_for_response(self, expected_id, match_response_id):
        # Long budget until the server proves it is up (first response), short
        # thereafter so ignored requests fail fast.
        effective_timeout = (
            self.timeout if self._first_response_seen else self.startup_timeout
        )
        deadline = time.perf_counter() + effective_timeout

        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                message = "STDIO response timed out"
                if match_response_id:
                    message = (
                        "STDIO response timed out waiting for "
                        f"response id {expected_id!r}"
                    )
                return ClientResponse(
                    status_code=None,
                    transport_error=message,
                    text=self._stderr_tail(),
                )

            try:
                line = self._stdout_queue.get(timeout=remaining)
            except queue.Empty:
                message = "STDIO response timed out"
                if match_response_id:
                    message = (
                        "STDIO response timed out waiting for "
                        f"response id {expected_id!r}"
                    )
                return ClientResponse(
                    status_code=None,
                    transport_error=message,
                    text=self._stderr_tail(),
                )

            response = self._parse_stdio_response(line)
            if not response.has_transport_error:
                # The server produced output, so it is up: switch to the short
                # per-request timeout for all subsequent requests.
                self._first_response_seen = True
            if not match_response_id:
                return response

            if self._response_matches_id(response, expected_id):
                return response

            if self._is_unrelated_stdout_message(response):
                continue

            return response

    def _write_line(self, raw_body):
        if self.process is None or self.process.poll() is not None:
            return "STDIO process is not running"

        if self.process.stdin is None:
            return "STDIO process stdin is not available"

        try:
            self.process.stdin.write(raw_body + "\n")
            self.process.stdin.flush()
            return None
        except Exception as e:
            return f"STDIO write failed: {e}"

    def _parse_stdio_response(self, line):
        text = line.rstrip("\r\n")
        try:
            body = json.loads(text)
        except ValueError:
            return ClientResponse(
                status_code=None,
                text=text,
                transport_error="STDIO response is not valid JSON",
            )

        return ClientResponse(status_code=200, body=body, text=text)

    @staticmethod
    def _response_matches_id(response: ClientResponse, expected_id) -> bool:
        if response.has_transport_error or not isinstance(response.body, dict):
            return False
        return "id" in response.body and response.body["id"] == expected_id

    @staticmethod
    def _is_unrelated_stdout_message(response: ClientResponse) -> bool:
        return (
            not response.has_transport_error
            and isinstance(response.body, dict)
            and "id" not in response.body
        )

    @staticmethod
    def _request_id_from_raw(raw_body):
        try:
            body = json.loads(raw_body)
        except (TypeError, ValueError):
            return None, False

        if isinstance(body, dict) and "id" in body:
            return body.get("id"), True

        return None, False

    def _read_stdout(self):
        if self.process is None or self.process.stdout is None:
            return

        for line in self.process.stdout:
            if line:
                self._stdout_queue.put(line)

    def _read_stderr(self):
        if self.process is None or self.process.stderr is None:
            return

        for line in self.process.stderr:
            if line:
                self._stderr_lines.append(line.rstrip("\r\n"))
                if len(self._stderr_lines) > 50:
                    self._stderr_lines.pop(0)

    def _stderr_tail(self):
        return "\n".join(self._stderr_lines[-5:])

    @staticmethod
    def _command_args(command):
        if isinstance(command, (list, tuple)):
            return list(command)

        if os.name == "nt":
            return command

        return shlex.split(command)

    @staticmethod
    def _is_notification(payload: dict[str, Any]) -> bool:
        method = payload.get("method")
        return isinstance(method, str) and method.startswith("notifications/")


class AsyncHttpMCPClient(BaseMCPClient):
    """Asynchronous HTTP JSON-RPC MCP client using aiohttp."""

    transport_type = "async_http"

    def __init__(self, server_url, timeout=5, protocol_version=None):
        super().__init__(timeout=timeout, protocol_version=protocol_version)
        self.server_url = server_url
        self.session = None

    async def __aenter__(self):
        import aiohttp
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            self.session = None

    def close(self):
        if self.session:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.session.close())
            except RuntimeError:
                asyncio.run(self.session.close())
            self.session = None

    def send_payload(self, payload):
        """Synchronous wrapper for test harness compatibility."""
        import asyncio
        return asyncio.run(self.send_payload_async(payload))

    def send_raw(self, raw_body):
        """Synchronous wrapper for test harness compatibility."""
        import asyncio
        return asyncio.run(self.send_raw_async(raw_body))

    async def send_payload_async(self, payload):
        import aiohttp
        import time
        headers = self._headers()
        start = time.perf_counter()
        close_session = False
        if not self.session:
            self.session = aiohttp.ClientSession()
            close_session = True

        try:
            async with self.session.post(
                self.server_url,
                json=payload,
                timeout=self.timeout,
                headers=headers,
            ) as response:
                text = await response.text()
                result = self._to_client_response_async(response.status, text)
        except Exception as e:
            result = ClientResponse(
                status_code=None,
                transport_error=str(e),
            )
        finally:
            if close_session:
                await self.session.close()
                self.session = None

        elapsed_ms = (time.perf_counter() - start) * 1000
        return self._record_response(result, elapsed_ms)

    async def send_raw_async(self, raw_body):
        import aiohttp
        import time
        headers = self._headers()
        start = time.perf_counter()
        close_session = False
        if not self.session:
            self.session = aiohttp.ClientSession()
            close_session = True

        try:
            async with self.session.post(
                self.server_url,
                data=raw_body,
                timeout=self.timeout,
                headers=headers,
            ) as response:
                text = await response.text()
                result = self._to_client_response_async(response.status, text)
        except Exception as e:
            result = ClientResponse(
                status_code=None,
                transport_error=str(e),
            )
        finally:
            if close_session:
                await self.session.close()
                self.session = None

        elapsed_ms = (time.perf_counter() - start) * 1000
        return self._record_response(result, elapsed_ms)

    def _headers(self):
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.protocol_version:
            headers["MCP-Protocol-Version"] = self.protocol_version
        return headers

    def _to_client_response_async(self, status_code, text):
        body = None
        if text.strip():
            try:
                body = json.loads(text)
            except ValueError:
                return ClientResponse(
                    status_code=status_code,
                    text=text,
                    transport_error="Response body is not valid JSON",
                )
        return ClientResponse(
            status_code=status_code,
            body=body,
            text=text,
        )


# Backward compatibility: existing framework imports MCPClient as the HTTP client.
MCPClient = HttpMCPClient
