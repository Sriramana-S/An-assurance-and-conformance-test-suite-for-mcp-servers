from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.models import ClientResponse, ValidationResult


PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
SERVER_ERROR_MIN = -32099
SERVER_ERROR_MAX = -32000

STANDARD_ERROR_CODES = {
    PARSE_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    INVALID_PARAMS,
    INTERNAL_ERROR,
}


class LifecycleState(str, Enum):
    CREATED = "created"
    INITIALIZE_SENT = "initialize_sent"
    INITIALIZED = "initialized"
    OPERATIONAL = "operational"


@dataclass
class RequestRecord:
    request_id: str | int
    method: str


@dataclass
class ProtocolConformanceEngine:
    protocol_version: str = "2025-11-25"
    state: LifecycleState = LifecycleState.CREATED
    used_request_ids: set[str | int] = field(default_factory=set)
    pending_requests: dict[str | int, RequestRecord] = field(default_factory=dict)
    negotiated_protocol_version: str | None = None

    def validate_request(self, message: Any) -> ValidationResult:
        base = self._validate_message_object(message)
        if not base.passed:
            return base

        if "id" not in message:
            return ValidationResult(False, "Request must include an id")

        request_id = message["id"]
        if not self._is_valid_request_id(request_id):
            return ValidationResult(
                False,
                "Request id must be a non-null string or integer",
                {"request_id": request_id},
            )

        if request_id in self.used_request_ids:
            return ValidationResult(
                False,
                "Request id has already been used in this session",
                {"request_id": request_id},
            )

        method = message["method"]
        lifecycle = self._validate_request_lifecycle(method)
        if not lifecycle.passed:
            return lifecycle

        self.used_request_ids.add(request_id)
        self.pending_requests[request_id] = RequestRecord(request_id, method)

        if method == "initialize":
            self.state = LifecycleState.INITIALIZE_SENT

        return ValidationResult(
            True,
            "Valid JSON-RPC request structure",
            {"method": method, "id": request_id, "state": self.state.value},
        )

    def validate_notification(self, message: Any) -> ValidationResult:
        base = self._validate_message_object(message)
        if not base.passed:
            return base

        if "id" in message:
            return ValidationResult(False, "Notification must not include an id")

        method = message["method"]
        if method == "notifications/initialized":
            if self.state != LifecycleState.INITIALIZED:
                return ValidationResult(
                    False,
                    "initialized notification must follow a successful initialize response",
                    {"state": self.state.value},
                )
            self.state = LifecycleState.OPERATIONAL

        return ValidationResult(
            True,
            "Valid JSON-RPC notification structure",
            {"method": method, "state": self.state.value},
        )

    def validate_response(
        self,
        response: ClientResponse,
        expected_id: str | int | None = None,
        expected_error_code: int | None = None,
        require_result: bool | None = None,
    ) -> ValidationResult:
        if response.has_transport_error:
            return ValidationResult(
                False,
                f"Transport error: {response.transport_error}",
            )

        message = response.body
        if message is None:
            return ValidationResult(False, "Missing JSON response body")

        if not isinstance(message, dict):
            return ValidationResult(False, "Response body is not a JSON object")

        if message.get("jsonrpc") != "2.0":
            return ValidationResult(False, "Invalid or missing JSON-RPC version")

        has_result = "result" in message
        has_error = "error" in message
        if has_result == has_error:
            return ValidationResult(
                False,
                "Response must contain exactly one of result or error",
            )

        response_id = message.get("id")
        if expected_id is not None and response_id != expected_id:
            return ValidationResult(
                False,
                "Response id does not match request id",
                {"expected_id": expected_id, "actual_id": response_id},
            )

        if expected_id is None and response_id in self.pending_requests:
            expected_id = response_id

        if (
            expected_id is not None
            and self.pending_requests
            and expected_id not in self.pending_requests
        ):
            return ValidationResult(
                False,
                "Response id does not match any pending request in this session",
                {"response_id": response_id},
            )

        if require_result is True and not has_result:
            return ValidationResult(False, "Expected success result, got error")

        if require_result is False and not has_error:
            return ValidationResult(False, "Expected error result, got success")

        if has_error:
            error_validation = self.validate_error_object(
                message["error"],
                expected_error_code,
            )
            if not error_validation.passed:
                return error_validation
            if expected_id in self.pending_requests:
                self.pending_requests.pop(expected_id)
            return error_validation

        if not isinstance(message["result"], dict):
            return ValidationResult(False, "Result field must be an object")

        request_record = self.pending_requests.pop(expected_id, None)
        if request_record and request_record.method == "initialize":
            version_validation = self._validate_initialize_result(message["result"])
            if not version_validation.passed:
                return version_validation
            self.negotiated_protocol_version = message["result"]["protocolVersion"]
            self.state = LifecycleState.INITIALIZED

        return ValidationResult(
            True,
            "Valid JSON-RPC response structure",
            {"id": response_id, "state": self.state.value},
        )

    def validate_error_object(
        self,
        error: Any,
        expected_error_code: int | None = None,
    ) -> ValidationResult:
        if not isinstance(error, dict):
            return ValidationResult(False, "Error field is not an object")

        code = error.get("code")
        if not isinstance(code, int) or isinstance(code, bool):
            return ValidationResult(False, "Error code is missing or not an integer")

        if expected_error_code is not None and code != expected_error_code:
            return ValidationResult(
                False,
                "Unexpected JSON-RPC error code",
                {"expected_code": expected_error_code, "actual_code": code},
            )

        if code not in STANDARD_ERROR_CODES and not (
            SERVER_ERROR_MIN <= code <= SERVER_ERROR_MAX
        ):
            return ValidationResult(
                False,
                "Error code is outside standard or reserved server-error range",
                {"actual_code": code},
            )

        message = error.get("message")
        if not isinstance(message, str) or not message:
            return ValidationResult(False, "Error message is missing or empty")

        return ValidationResult(
            True,
            "Valid JSON-RPC error response",
            {"actual_code": code},
        )

    def assert_operational(self) -> ValidationResult:
        if self.state != LifecycleState.OPERATIONAL:
            return ValidationResult(
                False,
                "Session is not operational; initialize and initialized are required",
                {"state": self.state.value},
            )
        return ValidationResult(True, "Session is operational")

    def _validate_message_object(self, message: Any) -> ValidationResult:
        if not isinstance(message, dict):
            return ValidationResult(False, "JSON-RPC message must be an object")

        if message.get("jsonrpc") != "2.0":
            return ValidationResult(False, "jsonrpc must be exactly 2.0")

        method = message.get("method")
        if not isinstance(method, str) or not method:
            return ValidationResult(False, "method must be a non-empty string")

        params = message.get("params", {})
        if params is not None and not isinstance(params, dict):
            return ValidationResult(False, "params must be an object when present")

        return ValidationResult(True, "Valid JSON-RPC message object")

    def _validate_request_lifecycle(self, method: str) -> ValidationResult:
        if self.state == LifecycleState.CREATED:
            if method != "initialize":
                return ValidationResult(
                    False,
                    "Initialization must be the first client request",
                    {"method": method, "state": self.state.value},
                )
            return ValidationResult(True, "Initialize request is allowed")

        if self.state == LifecycleState.INITIALIZE_SENT:
            if method == "ping":
                return ValidationResult(True, "Ping is allowed during initialization")
            return ValidationResult(
                False,
                "Client must wait for initialize response before normal requests",
                {"method": method, "state": self.state.value},
            )

        if self.state == LifecycleState.INITIALIZED:
            if method == "ping":
                return ValidationResult(True, "Ping is allowed before initialized")
            return ValidationResult(
                False,
                "Client must send notifications/initialized before normal requests",
                {"method": method, "state": self.state.value},
            )

        return ValidationResult(True, "Request is allowed in operation phase")

    def _validate_initialize_result(self, result: dict[str, Any]) -> ValidationResult:
        protocol_version = result.get("protocolVersion")
        if not isinstance(protocol_version, str) or not protocol_version:
            return ValidationResult(False, "Initialize result missing protocolVersion")

        if "capabilities" not in result or not isinstance(
            result["capabilities"],
            dict,
        ):
            return ValidationResult(False, "Initialize result missing capabilities")

        server_info = result.get("serverInfo")
        if not isinstance(server_info, dict):
            return ValidationResult(False, "Initialize result missing serverInfo")

        if not isinstance(server_info.get("name"), str) or not server_info["name"]:
            return ValidationResult(False, "serverInfo.name is missing or empty")

        if not isinstance(server_info.get("version"), str):
            return ValidationResult(False, "serverInfo.version is missing")

        return ValidationResult(True, "Valid initialize result")

    @staticmethod
    def _is_valid_request_id(value: Any) -> bool:
        if isinstance(value, bool):
            return False
        return isinstance(value, (str, int))
