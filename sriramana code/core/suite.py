from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

from core.client import BaseMCPClient
from core.conformance import ProtocolConformanceEngine
from core.models import AssuranceResult, ValidationResult
from core.validator import ProtocolValidator


PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602


@dataclass(frozen=True)
class AssuranceCase:
    name: str
    category: str
    severity: str
    runner: Callable[[BaseMCPClient, str], AssuranceResult]
    conformance_level: str = "MUST"
    spec_clause: str = ""


def initialize_params(protocol_version: str) -> dict[str, Any]:
    return {
        "protocolVersion": protocol_version,
        "capabilities": {},
        "clientInfo": {
            "name": "mcp-assurance-suite",
            "version": "1.0.0",
        },
    }


def request_payload(method: str, params=None, request_id=None) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
        "id": request_id,
    }


def notification_payload(method: str, params=None) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
    }


def _result_from_validation(
    case: AssuranceCase | str,
    category: str,
    severity: str,
    validation: ValidationResult,
    conformance_level: str = "MUST",
    spec_clause: str = "",
) -> AssuranceResult:
    name = case.name if isinstance(case, AssuranceCase) else case
    if validation.passed:
        return AssuranceResult.pass_result(
            name,
            category,
            validation.message,
            validation.details,
            severity,
            conformance_level=conformance_level,
            spec_clause=spec_clause,
        )
    # A failed SHOULD-level expectation is an advisory (WARN), not a hard
    # MUST violation (FAIL).
    if conformance_level == "SHOULD":
        return AssuranceResult.warn_result(
            name,
            category,
            validation.message,
            validation.details,
            severity,
            conformance_level=conformance_level,
            spec_clause=spec_clause,
        )
    return AssuranceResult.fail_result(
        name,
        category,
        validation.message,
        validation.details,
        severity,
        conformance_level=conformance_level,
        spec_clause=spec_clause,
    )


def send_validated_request(
    client: BaseMCPClient,
    engine: ProtocolConformanceEngine,
    method: str,
    params=None,
    request_id=None,
):
    if request_id is None:
        request_id = client._next_request_id()

    payload = request_payload(method, params, request_id)
    request_validation = engine.validate_request(payload)
    if not request_validation.passed:
        return None, request_id, request_validation

    return client.send_payload(payload), request_id, request_validation


def send_validated_notification(
    client: BaseMCPClient,
    engine: ProtocolConformanceEngine,
    method: str,
    params=None,
):
    payload = notification_payload(method, params)
    notification_validation = engine.validate_notification(payload)
    if not notification_validation.passed:
        return None, notification_validation

    return client.send_payload(payload), notification_validation


def perform_initialize(
    client: BaseMCPClient,
    protocol_version: str,
    engine: ProtocolConformanceEngine | None = None,
    send_initialized: bool = True,
):
    engine = engine or ProtocolConformanceEngine(protocol_version)
    request_id = client._next_request_id()
    response, _, request_validation = send_validated_request(
        client,
        engine,
        "initialize",
        initialize_params(protocol_version),
        request_id=request_id,
    )
    if not request_validation.passed:
        return response, request_validation

    validation = ProtocolValidator.validate_initialize_response(
        response,
        expected_id=request_id,
        engine=engine,
    )
    if validation.passed and send_initialized:
        _, initialized_validation = send_validated_notification(
            client,
            engine,
            "notifications/initialized",
        )
        if not initialized_validation.passed:
            return response, initialized_validation
    return response, validation


def run_initialize_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    engine = ProtocolConformanceEngine(protocol_version)
    _, validation = perform_initialize(
        client,
        protocol_version,
        engine=engine,
        send_initialized=False,
    )
    return _result_from_validation(
        "Initialize Handshake",
        "Protocol Conformance",
        "critical",
        validation,
    )


def run_initialized_notification_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    engine = ProtocolConformanceEngine(protocol_version)
    _, init_validation = perform_initialize(
        client,
        protocol_version,
        engine=engine,
        send_initialized=False,
    )
    if not init_validation.passed:
        return AssuranceResult.fail_result(
            "Initialized Notification",
            "Protocol Conformance",
            "Cannot test initialized notification because initialize failed",
            init_validation.details,
            "high",
        )

    response, notification_validation = send_validated_notification(
        client,
        engine,
        "notifications/initialized",
    )
    if not notification_validation.passed:
        return AssuranceResult.fail_result(
            "Initialized Notification",
            "Protocol Conformance",
            notification_validation.message,
            notification_validation.details,
            "high",
        )

    if response.has_transport_error:
        return AssuranceResult.fail_result(
            "Initialized Notification",
            "Protocol Conformance",
            f"Transport error: {response.transport_error}",
            severity="high",
        )

    if response.status_code in (200, 202, 204):
        return AssuranceResult.pass_result(
            "Initialized Notification",
            "Protocol Conformance",
            "Server accepted initialized notification",
            {"status_code": response.status_code},
            "high",
        )

    return AssuranceResult.fail_result(
        "Initialized Notification",
        "Protocol Conformance",
        "Server returned unexpected status for initialized notification",
        {"status_code": response.status_code},
        "high",
    )


def _declared_capabilities(init_response) -> dict[str, Any]:
    """The capabilities object the server advertised in its initialize result.

    Returns an empty dict when it cannot be read. Per MCP, tools/resources/
    prompts are OPTIONAL capabilities, declared by the presence of their key."""
    try:
        capabilities = init_response.body["result"].get("capabilities", {})
    except (AttributeError, TypeError, KeyError):
        return {}
    return capabilities if isinstance(capabilities, dict) else {}


def _capability_skip(
    test_name: str,
    category: str,
    capability: str,
) -> AssuranceResult:
    """A SKIP for a functional test whose capability the server did not declare,
    so optional-feature absence is not scored as a conformance failure."""
    return AssuranceResult.skip_result(
        test_name,
        category,
        f"Server did not declare the '{capability}' capability "
        f"('{capability}' methods are optional in MCP)",
    )


def run_tools_list_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    engine = ProtocolConformanceEngine(protocol_version)
    init_response, init_validation = perform_initialize(
        client, protocol_version, engine=engine
    )
    if not init_validation.passed:
        validation = init_validation
    elif "tools" not in _declared_capabilities(init_response):
        return _capability_skip(
            "Tools List Schema", "Functional Correctness", "tools"
        )
    else:
        response, request_id, request_validation = send_validated_request(
            client,
            engine,
            "tools/list",
            {},
        )
        validation = (
            ProtocolValidator.validate_tools_list(
                response,
                expected_id=request_id,
                engine=engine,
            )
            if request_validation.passed
            else request_validation
        )
    return _result_from_validation(
        "Tools List Schema",
        "Functional Correctness",
        "high",
        validation,
    )


def run_resources_list_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    engine = ProtocolConformanceEngine(protocol_version)
    init_response, init_validation = perform_initialize(
        client, protocol_version, engine=engine
    )
    if not init_validation.passed:
        validation = init_validation
    elif "resources" not in _declared_capabilities(init_response):
        return _capability_skip(
            "Resources List Schema", "Functional Correctness", "resources"
        )
    else:
        response, request_id, request_validation = send_validated_request(
            client,
            engine,
            "resources/list",
            {},
        )
        validation = (
            ProtocolValidator.validate_resources_list(
                response,
                expected_id=request_id,
                engine=engine,
            )
            if request_validation.passed
            else request_validation
        )
    return _result_from_validation(
        "Resources List Schema",
        "Functional Correctness",
        "medium",
        validation,
    )


def run_prompts_list_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    engine = ProtocolConformanceEngine(protocol_version)
    init_response, init_validation = perform_initialize(
        client, protocol_version, engine=engine
    )
    if not init_validation.passed:
        validation = init_validation
    elif "prompts" not in _declared_capabilities(init_response):
        return _capability_skip(
            "Prompts List Schema", "Functional Correctness", "prompts"
        )
    else:
        response, request_id, request_validation = send_validated_request(
            client,
            engine,
            "prompts/list",
            {},
        )
        validation = (
            ProtocolValidator.validate_prompts_list(
                response,
                expected_id=request_id,
                engine=engine,
            )
            if request_validation.passed
            else request_validation
        )
    return _result_from_validation(
        "Prompts List Schema",
        "Functional Correctness",
        "medium",
        validation,
    )


def run_resources_read_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    engine = ProtocolConformanceEngine(protocol_version)
    init_response, init_validation = perform_initialize(
        client, protocol_version, engine=engine
    )
    if not init_validation.passed:
        return AssuranceResult.fail_result(
            "Resource Read Validation",
            "Functional Correctness",
            "Cannot read resource because initialize failed",
            init_validation.details,
            "medium",
        )

    if "resources" not in _declared_capabilities(init_response):
        return _capability_skip(
            "Resource Read Validation", "Functional Correctness", "resources"
        )

    # First list resources to find a valid URI to read
    list_response, list_id, list_request_val = send_validated_request(
        client,
        engine,
        "resources/list",
        {},
    )
    list_val = (
        ProtocolValidator.validate_resources_list(
            list_response,
            expected_id=list_id,
            engine=engine,
        )
        if list_request_val.passed
        else list_request_val
    )
    if not list_val.passed:
        return AssuranceResult.fail_result(
            "Resource Read Validation",
            "Functional Correctness",
            "Cannot read resource because resources/list failed",
            list_val.details,
            "medium",
        )

    resources = list_response.body["result"].get("resources", [])
    if not resources:
        return AssuranceResult.skip_result(
            "Resource Read Validation",
            "Functional Correctness",
            "No resources advertised by this server to read",
        )

    # Read the first advertised resource
    target_uri = resources[0]["uri"]
    response, request_id, request_validation = send_validated_request(
        client,
        engine,
        "resources/read",
        {"uri": target_uri},
    )
    validation = (
        ProtocolValidator.validate_resource_read(
            response,
            expected_id=request_id,
            engine=engine,
        )
        if request_validation.passed
        else request_validation
    )
    return _result_from_validation(
        "Resource Read Validation",
        "Functional Correctness",
        "medium",
        validation,
    )


def run_prompts_get_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    engine = ProtocolConformanceEngine(protocol_version)
    init_response, init_validation = perform_initialize(
        client, protocol_version, engine=engine
    )
    if not init_validation.passed:
        return AssuranceResult.fail_result(
            "Prompt Get Validation",
            "Functional Correctness",
            "Cannot get prompt because initialize failed",
            init_validation.details,
            "medium",
        )

    if "prompts" not in _declared_capabilities(init_response):
        return _capability_skip(
            "Prompt Get Validation", "Functional Correctness", "prompts"
        )

    # First list prompts to find a valid name to fetch
    list_response, list_id, list_request_val = send_validated_request(
        client,
        engine,
        "prompts/list",
        {},
    )
    list_val = (
        ProtocolValidator.validate_prompts_list(
            list_response,
            expected_id=list_id,
            engine=engine,
        )
        if list_request_val.passed
        else list_request_val
    )
    if not list_val.passed:
        return AssuranceResult.fail_result(
            "Prompt Get Validation",
            "Functional Correctness",
            "Cannot get prompt because prompts/list failed",
            list_val.details,
            "medium",
        )

    prompts = list_response.body["result"].get("prompts", [])
    if not prompts:
        return AssuranceResult.skip_result(
            "Prompt Get Validation",
            "Functional Correctness",
            "No prompts advertised by this server to fetch",
        )

    # Fetch the first advertised prompt
    target_prompt = prompts[0]
    prompt_name = target_prompt["name"]
    arguments = {}
    if prompt_name == "summarise_assurance_result":
        arguments = {"finding": "Initialize handshake passed"}
    elif target_prompt.get("arguments"):
        for arg in target_prompt["arguments"]:
            if arg.get("required"):
                arguments[arg["name"]] = "synthetic_value"

    response, request_id, request_validation = send_validated_request(
        client,
        engine,
        "prompts/get",
        {"name": prompt_name, "arguments": arguments},
    )
    validation = (
        ProtocolValidator.validate_prompt_get(
            response,
            expected_id=request_id,
            engine=engine,
        )
        if request_validation.passed
        else request_validation
    )
    return _result_from_validation(
        "Prompt Get Validation",
        "Functional Correctness",
        "medium",
        validation,
    )


def run_calculator_tool_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    engine = ProtocolConformanceEngine(protocol_version)
    init_response, init_validation = perform_initialize(
        client, protocol_version, engine=engine
    )
    if not init_validation.passed:
        return AssuranceResult.fail_result(
            "Advertised Tool Execution",
            "Functional Correctness",
            "Cannot execute tool because initialize failed",
            init_validation.details,
            "high",
        )

    if "tools" not in _declared_capabilities(init_response):
        return _capability_skip(
            "Advertised Tool Execution", "Functional Correctness", "tools"
        )

    tools_response, list_id, request_validation = send_validated_request(
        client,
        engine,
        "tools/list",
        {},
    )
    if not request_validation.passed:
        list_validation = request_validation
    else:
        list_validation = ProtocolValidator.validate_tools_list(
            tools_response,
            expected_id=list_id,
            engine=engine,
        )
    if not list_validation.passed:
        return AssuranceResult.fail_result(
            "Advertised Tool Execution",
            "Functional Correctness",
            "Cannot execute tool because tools/list is invalid",
            list_validation.details,
            "high",
        )

    tools = tools_response.body["result"].get("tools", [])
    calculator = next(
        (tool for tool in tools if tool.get("name") == "calculator"),
        None,
    )
    if calculator is None:
        return AssuranceResult.skip_result(
            "Advertised Tool Execution",
            "Functional Correctness",
            "No calculator tool advertised by this server",
        )

    response, request_id, request_validation = send_validated_request(
        client,
        engine,
        "tools/call",
        {
            "name": "calculator",
            "arguments": {
                "operation": "add",
                "a": 2,
                "b": 3,
            },
        },
    )
    validation = (
        ProtocolValidator.validate_tool_call(
            response,
            expected_id=request_id,
            engine=engine,
        )
        if request_validation.passed
        else request_validation
    )
    return _result_from_validation(
        "Advertised Tool Execution",
        "Functional Correctness",
        "high",
        validation,
    )


run_tool_execution_test = run_calculator_tool_test


def run_unknown_method_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    engine = ProtocolConformanceEngine(protocol_version)
    _, init_validation = perform_initialize(client, protocol_version, engine=engine)
    if not init_validation.passed:
        validation = init_validation
    else:
        response, request_id, request_validation = send_validated_request(
            client,
            engine,
            "assurance/unknownMethod",
            {},
        )
        validation = (
            ProtocolValidator.validate_error_response(
                response,
                expected_code=METHOD_NOT_FOUND,
                expected_id=request_id,
                engine=engine,
            )
            if request_validation.passed
            else request_validation
        )
    return _result_from_validation(
        "Unknown Method Rejection",
        "Protocol Conformance",
        "high",
        validation,
    )


SILENT_DROP_MESSAGE = (
    "Server returned no response to malformed input (transport-layer silent "
    "drop) — advisory: explicit JSON-RPC error feedback recommended."
)


def _negative_validation_result(
    name: str,
    category: str,
    severity: str,
    validation: ValidationResult,
    response: "ClientResponse",
    conformance_level: str = "MUST",
    spec_clause: str = "",
) -> AssuranceResult:
    """Build the result for a negative-validation test, distinguishing a
    *silent drop* (timeout / no JSON body — the SDK transport discarded the
    malformed frame) from a *wrong response* (the server replied incorrectly).

    A silent drop is a softer conformance signal than a wrong response, so it
    is scored as an advisory WARN rather than a hard FAIL. conformance_level
    stays MUST (the spec still requires error handling)."""
    if validation.passed:
        return AssuranceResult.pass_result(
            name, category, validation.message, validation.details, severity,
            conformance_level=conformance_level, spec_clause=spec_clause,
        )
    if response.has_transport_error or response.body is None:
        return AssuranceResult.warn_result(
            name, category, SILENT_DROP_MESSAGE, validation.details, severity,
            conformance_level=conformance_level, spec_clause=spec_clause,
        )
    # The server replied with the wrong thing (e.g. a success body or wrong
    # error code for a garbage request) — a genuine FAIL.
    return AssuranceResult.fail_result(
        name, category, validation.message, validation.details, severity,
        conformance_level=conformance_level, spec_clause=spec_clause,
    )


def _run_invalid_payload_case(
    client: BaseMCPClient,
    name: str,
    payload: dict[str, Any],
    expected_id,
) -> AssuranceResult:
    response = client.send_payload(payload)
    validation = ProtocolValidator.validate_error_response(
        response,
        expected_code=INVALID_REQUEST,
        expected_id=expected_id,
    )
    return _negative_validation_result(
        name,
        "Basic Security Validation",
        "high",
        validation,
        response,
    )


def _run_error_payload_case(
    client: BaseMCPClient,
    name: str,
    payload: dict[str, Any],
    expected_code: int,
    expected_id=None,
    category="Advanced Negative Validation",
    conformance_level: str = "MUST",
    spec_clause: str = "",
) -> AssuranceResult:
    response = client.send_payload(payload)
    validation = ProtocolValidator.validate_error_response(
        response,
        expected_code=expected_code,
        expected_id=expected_id,
    )
    return _negative_validation_result(
        name,
        category,
        "high",
        validation,
        response,
        conformance_level=conformance_level,
        spec_clause=spec_clause,
    )


def _run_raw_error_case(
    client: BaseMCPClient,
    name: str,
    raw_body: str,
    expected_code: int,
) -> AssuranceResult:
    response = client.send_raw(raw_body)
    validation = ProtocolValidator.validate_error_response(
        response,
        expected_code=expected_code,
    )
    return _negative_validation_result(
        name,
        "Advanced Negative Validation",
        "high",
        validation,
        response,
    )


def run_null_method_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    return _run_invalid_payload_case(
        client,
        "Null Method Rejection",
        {"jsonrpc": "2.0", "method": None, "id": "null-method"},
        "null-method",
    )


def run_invalid_method_type_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    return _run_invalid_payload_case(
        client,
        "Invalid Method Type Rejection",
        {"jsonrpc": "2.0", "method": 12345, "id": "numeric-method"},
        "numeric-method",
    )


def run_empty_method_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    return _run_invalid_payload_case(
        client,
        "Empty Method Rejection",
        {"jsonrpc": "2.0", "method": "", "id": "empty-method"},
        "empty-method",
    )


def run_missing_jsonrpc_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    return _run_invalid_payload_case(
        client,
        "Missing JSON-RPC Version Rejection",
        {"method": "initialize", "id": "missing-version"},
        "missing-version",
    )


def run_invalid_jsonrpc_version_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    return _run_invalid_payload_case(
        client,
        "Invalid JSON-RPC Version Rejection",
        {"jsonrpc": "1.0", "method": "initialize", "id": "bad-version"},
        "bad-version",
    )


def run_malformed_json_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    return _run_raw_error_case(
        client,
        "Malformed JSON Parse Error",
        '{"jsonrpc":"2.0","method":"initialize",',
        PARSE_ERROR,
    )


def run_non_object_json_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    return _run_raw_error_case(
        client,
        "Non-Object JSON Rejection",
        '"not a json-rpc object"',
        INVALID_REQUEST,
    )


def run_missing_method_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    return _run_error_payload_case(
        client,
        "Missing Method Field Rejection",
        {"jsonrpc": "2.0", "id": "missing-method"},
        INVALID_REQUEST,
        "missing-method",
    )


def _run_notification_silence_case(
    client: BaseMCPClient,
    name: str,
    payload: dict[str, Any],
) -> AssuranceResult:
    """Under JSON-RPC 2.0 a message with no id (or a null id) is a
    notification, and the server MUST NOT send any response. Silence
    (a transport timeout or an empty body) is therefore the correct,
    passing behaviour; only an actual response body is a failure."""
    response = client.send_payload(payload)

    if response.has_transport_error:
        return AssuranceResult.pass_result(
            name,
            "Protocol Conformance",
            "Server sent no response, correctly treating the id-less "
            "message as a notification",
            {"transport_error": response.transport_error},
            "high",
        )

    if response.body is None:
        return AssuranceResult.pass_result(
            name,
            "Protocol Conformance",
            "Server returned an empty body, correctly treating the "
            "id-less message as a notification",
            {"status_code": response.status_code},
            "high",
        )

    return AssuranceResult.fail_result(
        name,
        "Protocol Conformance",
        "Server responded to an id-less notification; per JSON-RPC 2.0 "
        "it MUST stay silent",
        {"status_code": response.status_code, "body": response.body},
        "high",
    )


def run_missing_request_id_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    return _run_notification_silence_case(
        client,
        "Missing Id Treated as Notification",
        {"jsonrpc": "2.0", "method": "tools/list", "params": {}},
    )


def run_null_request_id_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    return _run_notification_silence_case(
        client,
        "Null Id Treated as Notification",
        {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": initialize_params(protocol_version),
            "id": None,
        },
    )


def run_params_array_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    return _run_error_payload_case(
        client,
        "Array Params Rejection",
        {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": [],
            "id": "array-params",
        },
        INVALID_REQUEST,
        "array-params",
    )


def run_unsupported_protocol_version_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    """The MCP spec requires version negotiation: when the client asks for
    a protocol version the server does not support, the server MAY reject
    it with INVALID_PARAMS, or it MAY respond successfully with a version it
    does support. Both outcomes are conformant; only a crash, a malformed
    response, or an unexpected error code is a failure."""
    name = "Unsupported Protocol Version Handling"
    category = "Advanced Negative Validation"
    severity = "high"
    requested_version = "1900-01-01"
    request_id = "unsupported-protocol"

    payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": initialize_params(requested_version),
        "id": request_id,
    }
    response = client.send_payload(payload)

    if response.has_transport_error:
        return AssuranceResult.fail_result(
            name,
            category,
            f"Transport error while negotiating protocol version: "
            f"{response.transport_error}",
            {"transport_error": response.transport_error},
            severity,
        )

    message = response.body
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return AssuranceResult.fail_result(
            name,
            category,
            "Server returned a malformed response to an unsupported "
            "protocol version request",
            {"status_code": response.status_code, "body": message},
            severity,
        )

    has_result = "result" in message
    has_error = "error" in message
    if has_result == has_error:
        return AssuranceResult.fail_result(
            name,
            category,
            "Response must contain exactly one of result or error",
            {"body": message},
            severity,
        )

    # Outcome 1: the server performed version negotiation and replied with
    # a (different) version it actually supports.
    if has_result:
        result = message["result"]
        negotiated = (
            result.get("protocolVersion") if isinstance(result, dict) else None
        )
        if not isinstance(negotiated, str) or not negotiated:
            return AssuranceResult.fail_result(
                name,
                category,
                "Server returned a success response without a valid "
                "protocolVersion during negotiation",
                {"body": message},
                severity,
            )
        if negotiated == requested_version:
            return AssuranceResult.fail_result(
                name,
                category,
                f"Server echoed back the unsupported protocol version "
                f"'{requested_version}' instead of negotiating a supported one",
                {"protocolVersion": negotiated},
                severity,
            )
        return AssuranceResult.pass_result(
            name,
            category,
            f"Server negotiated supported protocol version '{negotiated}' "
            f"after client requested unsupported '{requested_version}'",
            {
                "requested_version": requested_version,
                "negotiated_version": negotiated,
            },
            severity,
        )

    # Outcome 2: the server rejected the unsupported version with an error.
    error_validation = ProtocolValidator.validate_error_object(message["error"])
    if not error_validation.passed:
        return AssuranceResult.fail_result(
            name,
            category,
            f"Server returned a malformed error object: "
            f"{error_validation.message}",
            {"error": message["error"]},
            severity,
        )

    code = message["error"]["code"]
    if code != INVALID_PARAMS:
        return AssuranceResult.fail_result(
            name,
            category,
            f"Server rejected the unsupported version with unexpected error "
            f"code {code} (expected INVALID_PARAMS {INVALID_PARAMS})",
            {"actual_code": code, "expected_code": INVALID_PARAMS},
            severity,
        )

    return AssuranceResult.pass_result(
        name,
        category,
        f"Server rejected unsupported protocol version '{requested_version}' "
        f"with INVALID_PARAMS ({INVALID_PARAMS})",
        {"requested_version": requested_version, "error_code": code},
        severity,
    )


def run_missing_initialize_client_info_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    return _run_error_payload_case(
        client,
        "Missing Initialize Client Info Rejection",
        {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": protocol_version,
                "capabilities": {},
            },
            "id": "missing-client-info",
        },
        INVALID_PARAMS,
        "missing-client-info",
        conformance_level="SHOULD",
        spec_clause="MCP spec 2025-11-25 §3.1 — clientInfo field",
    )


def run_invalid_tool_parameters_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    spec_clause = "MCP spec 2025-11-25 §5.1 — parameter validation"
    engine = ProtocolConformanceEngine(protocol_version)
    _, init_validation = perform_initialize(client, protocol_version, engine=engine)
    if not init_validation.passed:
        return AssuranceResult.fail_result(
            "Invalid Tool Parameters Rejection",
            "Advanced Negative Validation",
            "Cannot test invalid tool parameters because initialize failed",
            init_validation.details,
            "high",
            conformance_level="SHOULD",
            spec_clause=spec_clause,
        )

    response, request_id, request_validation = send_validated_request(
        client,
        engine,
        "tools/call",
        {
            "name": "calculator",
            "arguments": {
                "operation": "add",
                "a": "not-a-number",
                "b": 3,
            },
        },
    )
    validation = (
        ProtocolValidator.validate_error_response(
            response,
            expected_code=INVALID_PARAMS,
            expected_id=request_id,
            engine=engine,
        )
        if request_validation.passed
        else request_validation
    )
    return _result_from_validation(
        "Invalid Tool Parameters Rejection",
        "Advanced Negative Validation",
        "high",
        validation,
        conformance_level="SHOULD",
        spec_clause=spec_clause,
    )


def run_string_request_id_echo_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    engine = ProtocolConformanceEngine(protocol_version)
    request_id = "assurance-string-id"
    response, _, request_validation = send_validated_request(
        client,
        engine,
        "initialize",
        initialize_params(protocol_version),
        request_id=request_id,
    )
    validation = (
        ProtocolValidator.validate_initialize_response(
            response,
            expected_id=request_id,
            engine=engine,
        )
        if request_validation.passed
        else request_validation
    )
    return _result_from_validation(
        "String Request Id Echo",
        "Interoperability",
        "medium",
        validation,
    )


def run_capability_consistency_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    engine = ProtocolConformanceEngine(protocol_version)
    init_response, init_validation = perform_initialize(
        client,
        protocol_version,
        engine=engine,
    )
    if not init_validation.passed:
        return AssuranceResult.fail_result(
            "Declared Capability Consistency",
            "Interoperability",
            "Cannot inspect capabilities because initialize failed",
            init_validation.details,
            "high",
        )

    capabilities = init_response.body["result"].get("capabilities", {})
    checks: list[tuple[str, Callable]] = []
    if "tools" in capabilities:
        checks.append(("tools/list", ProtocolValidator.validate_tools_list))
    if "resources" in capabilities:
        checks.append(("resources/list", ProtocolValidator.validate_resources_list))
    if "prompts" in capabilities:
        checks.append(("prompts/list", ProtocolValidator.validate_prompts_list))

    if not checks:
        return AssuranceResult.skip_result(
            "Declared Capability Consistency",
            "Interoperability",
            "Server did not declare tools, resources or prompts capabilities",
        )

    failures = []
    for method, validator in checks:
        response, request_id, request_validation = send_validated_request(
            client,
            engine,
            method,
            {},
        )
        validation = (
            validator(response, expected_id=request_id, engine=engine)
            if request_validation.passed
            else request_validation
        )
        if not validation.passed:
            failures.append(f"{method}: {validation.message}")

    if failures:
        return AssuranceResult.fail_result(
            "Declared Capability Consistency",
            "Interoperability",
            "; ".join(failures),
            {"capabilities": list(capabilities.keys())},
            "high",
        )

    return AssuranceResult.pass_result(
        "Declared Capability Consistency",
        "Interoperability",
        "Declared server capabilities are backed by working list methods",
        {"capabilities": list(capabilities.keys())},
        "medium",
    )


def run_pagination_cursor_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    """SHOULD: a tools/list with an unknown/invalid cursor must be handled
    gracefully - either ignored (valid result) or rejected with a valid error
    code. A crash or malformed response is an advisory WARN."""
    name = "Pagination Cursor Handling"
    category = "Protocol Conformance"
    spec_clause = "MCP spec 2025-11-25 §5 — pagination cursor"
    engine = ProtocolConformanceEngine(protocol_version)
    _, init_validation = perform_initialize(client, protocol_version, engine=engine)
    if not init_validation.passed:
        return AssuranceResult.warn_result(
            name, category, "Cannot test pagination because initialize failed",
            init_validation.details, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)

    response, _, request_validation = send_validated_request(
        client, engine, "tools/list", {"cursor": "invalid-cursor-zzz-999"})
    if not request_validation.passed:
        return AssuranceResult.warn_result(
            name, category, request_validation.message, request_validation.details,
            "medium", conformance_level="SHOULD", spec_clause=spec_clause)
    if response.has_transport_error:
        return AssuranceResult.warn_result(
            name, category,
            f"No/garbled response to an unknown cursor: {response.transport_error}",
            {"transport_error": response.transport_error}, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)

    body = response.body
    if not isinstance(body, dict):
        return AssuranceResult.warn_result(
            name, category, "Malformed response to an unknown cursor",
            {"body": body}, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)
    if "result" in body:
        return AssuranceResult.pass_result(
            name, category,
            "Server ignored the unknown cursor and returned a valid result",
            {"handling": "ignored"}, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)
    if "error" in body:
        err = body.get("error")
        code = err.get("code") if isinstance(err, dict) else None
        if isinstance(code, int):
            return AssuranceResult.pass_result(
                name, category,
                f"Server rejected the unknown cursor with error code {code}",
                {"handling": "error", "code": code}, "medium",
                conformance_level="SHOULD", spec_clause=spec_clause)
        return AssuranceResult.warn_result(
            name, category, "Error object without a valid integer code",
            {"error": err}, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)
    return AssuranceResult.warn_result(
        name, category, "Response contained neither result nor error",
        {"body": body}, "medium",
        conformance_level="SHOULD", spec_clause=spec_clause)


def run_capability_gated_tool_call_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    """MUST: if the server declares the tools capability, calling a
    non-existent tool must return an error (a JSON-RPC error or a result with
    isError=true) - never a clean success."""
    name = "Capability-Gated Tool Call"
    category = "Functional Correctness"
    spec_clause = "MCP spec 2025-11-25 §3.2 — strict capability gating"
    engine = ProtocolConformanceEngine(protocol_version)
    init_response, init_validation = perform_initialize(
        client, protocol_version, engine=engine)
    if not init_validation.passed:
        return AssuranceResult.fail_result(
            name, category, "Cannot test capability gating because initialize failed",
            init_validation.details, "high",
            conformance_level="MUST", spec_clause=spec_clause)

    if "tools" not in _declared_capabilities(init_response):
        return _capability_skip(name, category, "tools")

    response, _, request_validation = send_validated_request(
        client, engine, "tools/call",
        {"name": "__nonexistent_tool_zzz__", "arguments": {}})
    if not request_validation.passed:
        return AssuranceResult.fail_result(
            name, category, request_validation.message, request_validation.details,
            "high", conformance_level="MUST", spec_clause=spec_clause)
    if response.has_transport_error:
        return AssuranceResult.fail_result(
            name, category,
            f"Transport error calling a non-existent tool: {response.transport_error}",
            {"transport_error": response.transport_error}, "high",
            conformance_level="MUST", spec_clause=spec_clause)

    body = response.body
    if isinstance(body, dict):
        if "error" in body:
            err = body.get("error")
            code = err.get("code") if isinstance(err, dict) else None
            return AssuranceResult.pass_result(
                name, category,
                "Server returned a JSON-RPC error for a non-existent tool",
                {"code": code}, "high",
                conformance_level="MUST", spec_clause=spec_clause)
        result = body.get("result")
        if isinstance(result, dict) and result.get("isError") is True:
            return AssuranceResult.pass_result(
                name, category,
                "Server returned isError=true for a non-existent tool",
                {"isError": True}, "high",
                conformance_level="MUST", spec_clause=spec_clause)
    return AssuranceResult.fail_result(
        name, category,
        "Server returned a non-error response for a non-existent tool",
        {"body": body}, "high",
        conformance_level="MUST", spec_clause=spec_clause)


def run_tools_list_next_cursor_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    """SHOULD: if a tools/list response carries a nextCursor field it must be a
    string. Absent or correctly-typed is PASS; present-but-wrong-type is WARN."""
    name = "Tools List Next Cursor"
    category = "Protocol Conformance"
    spec_clause = "MCP spec 2025-11-25 §5 — nextCursor in list responses"
    engine = ProtocolConformanceEngine(protocol_version)
    _, init_validation = perform_initialize(client, protocol_version, engine=engine)
    if not init_validation.passed:
        return AssuranceResult.warn_result(
            name, category, "Cannot test nextCursor because initialize failed",
            init_validation.details, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)

    response, _, request_validation = send_validated_request(
        client, engine, "tools/list", {})
    if not request_validation.passed or response.has_transport_error:
        return AssuranceResult.warn_result(
            name, category, "Could not obtain a tools/list response to inspect",
            {"transport_error": response.transport_error}, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)

    body = response.body
    result = body.get("result") if isinstance(body, dict) else None
    if not isinstance(result, dict) or "nextCursor" not in result:
        return AssuranceResult.pass_result(
            name, category, "No nextCursor field present (acceptable)",
            {"nextCursor": "absent"}, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)
    nc = result["nextCursor"]
    if isinstance(nc, str):
        return AssuranceResult.pass_result(
            name, category, "nextCursor is a string as required",
            {"nextCursor_type": "str"}, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)
    return AssuranceResult.warn_result(
        name, category,
        f"nextCursor present but is {type(nc).__name__}, not a string",
        {"nextCursor_type": type(nc).__name__}, "medium",
        conformance_level="SHOULD", spec_clause=spec_clause)


def run_server_info_completeness_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    """SHOULD: the initialize result.serverInfo should carry both a non-empty
    name and a non-empty version string. Missing/empty version is an advisory
    WARN."""
    name = "Server Info Completeness"
    category = "Protocol Conformance"
    spec_clause = "MCP spec 2025-11-25 §3.1 — serverInfo fields"
    engine = ProtocolConformanceEngine(protocol_version)
    init_response, init_validation = perform_initialize(
        client, protocol_version, engine=engine)
    if not init_validation.passed:
        return AssuranceResult.warn_result(
            name, category, "Cannot inspect serverInfo because initialize failed",
            init_validation.details, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)

    body = init_response.body
    result = body.get("result") if isinstance(body, dict) else None
    server_info = result.get("serverInfo") if isinstance(result, dict) else None
    if not isinstance(server_info, dict):
        return AssuranceResult.warn_result(
            name, category, "serverInfo is missing or not an object",
            {"serverInfo": server_info}, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)

    nm = server_info.get("name")
    ver = server_info.get("version")
    name_ok = isinstance(nm, str) and bool(nm)
    version_ok = isinstance(ver, str) and bool(ver)
    if name_ok and version_ok:
        return AssuranceResult.pass_result(
            name, category, "serverInfo has both a name and a version",
            {"name": nm, "version": ver}, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)
    return AssuranceResult.warn_result(
        name, category,
        "serverInfo is incomplete (name or version missing/empty)",
        {"name": nm, "version": ver}, "medium",
        conformance_level="SHOULD", spec_clause=spec_clause)


# --------------------------------------------------------------------------- #
# Authorization Conformance (MCP spec 2025-11-25 §2.4 / §6.3)
#
# These are protocol-conformance checks, NOT penetration tests. They probe how
# an HTTP-transport server handles the MCP-Protocol-Version header and the
# OAuth 2.1 discovery surface, documenting the server's enforcement policy
# rather than attacking it. The MCP authorization model is defined for the HTTP
# transport, so header/status/discovery checks SKIP on STDIO targets (there is
# no HTTP header or status code to inspect there).
# --------------------------------------------------------------------------- #

AUTH_CATEGORY = "Authorization Conformance"


def _http_server_url(client: BaseMCPClient) -> str | None:
    """Return the server URL when this is an HTTP client, else None (STDIO)."""
    if getattr(client, "transport_type", None) == "http":
        return getattr(client, "server_url", None)
    return None


def _http_origin(url: str) -> str:
    """Strip any path/query so well-known endpoints resolve from the origin."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _parse_response_json(resp: "requests.Response"):
    """(parsed_body, ok). ok is False when the body is empty or not valid JSON."""
    text = (resp.text or "").strip()
    if not text:
        return None, False
    try:
        return resp.json(), True
    except ValueError:
        return None, False


def _valid_initialize_body(protocol_version: str, request_id: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": initialize_params(protocol_version),
        "id": request_id,
    }


def run_protocol_version_header_required_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    """MUST: the server must HANDLE an initialize sent without the
    MCP-Protocol-Version header without crashing. Both rejecting it (enforcing)
    and accepting it (permissive) are conformant; only a transport crash fails.
    This documents the server's enforcement policy rather than requiring
    rejection."""
    name = "Protocol Version Header Enforcement"
    spec_clause = (
        "MCP spec 2025-11-25 §2.4 — MCP-Protocol-Version header required"
    )
    body = _valid_initialize_body(protocol_version, "auth-no-version-header")

    server_url = _http_server_url(client)
    if server_url is None:
        # STDIO has no HTTP headers, so the request is by definition sent
        # without the version header; evaluate the JSON-RPC response.
        response = client.send_payload(body)
        return _version_header_verdict(
            name, spec_clause,
            transport_error=response.transport_error,
            status_code=response.status_code,
            json_body=response.body,
        )

    try:
        resp = requests.post(
            server_url, json=body, timeout=getattr(client, "timeout", 5),
            headers={"Accept": "application/json",
                     "Content-Type": "application/json"},
        )
    except requests.RequestException as exc:
        return AssuranceResult.fail_result(
            name, AUTH_CATEGORY,
            f"Transport error sending initialize without version header: {exc}",
            {"transport_error": str(exc)}, "high",
            conformance_level="MUST", spec_clause=spec_clause)

    json_body, _ = _parse_response_json(resp)
    return _version_header_verdict(
        name, spec_clause,
        transport_error=None,
        status_code=resp.status_code,
        json_body=json_body,
    )


def _version_header_verdict(name, spec_clause, *, transport_error,
                            status_code, json_body) -> AssuranceResult:
    if transport_error:
        return AssuranceResult.fail_result(
            name, AUTH_CATEGORY,
            f"Transport error (server crashed) without version header: "
            f"{transport_error}",
            {"transport_error": transport_error}, "high",
            conformance_level="MUST", spec_clause=spec_clause)
    if status_code is not None and 400 <= status_code < 500:
        return AssuranceResult.pass_result(
            name, AUTH_CATEGORY,
            "Server enforces version header (rejected)",
            {"status_code": status_code, "policy": "enforcing"}, "high",
            conformance_level="MUST", spec_clause=spec_clause)
    if isinstance(json_body, dict) and "error" in json_body:
        return AssuranceResult.pass_result(
            name, AUTH_CATEGORY,
            "Server enforces version header (rejected)",
            {"policy": "enforcing", "error": json_body.get("error")}, "high",
            conformance_level="MUST", spec_clause=spec_clause)
    if isinstance(json_body, dict) and "result" in json_body:
        return AssuranceResult.pass_result(
            name, AUTH_CATEGORY,
            "Server accepts requests without version header (permissive)",
            {"status_code": status_code, "policy": "permissive"}, "high",
            conformance_level="MUST", spec_clause=spec_clause)
    return AssuranceResult.warn_result(
        name, AUTH_CATEGORY,
        "Server returned malformed response",
        {"status_code": status_code, "body": json_body}, "high",
        conformance_level="MUST", spec_clause=spec_clause)


def run_invalid_protocol_version_header_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    """SHOULD: an initialize carrying a clearly-invalid MCP-Protocol-Version
    header ('0.0.0') should be rejected or negotiated down to a supported
    version. Echoing the invalid version back unchanged is an advisory WARN."""
    name = "Invalid Protocol Version Header Handling"
    spec_clause = "MCP spec 2025-11-25 §2.4 — version header validation"

    server_url = _http_server_url(client)
    if server_url is None:
        return AssuranceResult.skip_result(
            name, AUTH_CATEGORY,
            "Version header validation applies to HTTP transport only "
            "(no header on STDIO)",
            conformance_level="SHOULD", spec_clause=spec_clause)

    body = _valid_initialize_body(protocol_version, "auth-bad-version-header")
    try:
        resp = requests.post(
            server_url, json=body, timeout=getattr(client, "timeout", 5),
            headers={"Accept": "application/json",
                     "Content-Type": "application/json",
                     "MCP-Protocol-Version": "0.0.0"},
        )
    except requests.RequestException as exc:
        return AssuranceResult.fail_result(
            name, AUTH_CATEGORY,
            f"Transport error sending initialize with invalid version header: "
            f"{exc}",
            {"transport_error": str(exc)}, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)

    json_body, _ = _parse_response_json(resp)
    if isinstance(json_body, dict) and "error" in json_body:
        return AssuranceResult.pass_result(
            name, AUTH_CATEGORY,
            "Server rejected the invalid version header with an error",
            {"error": json_body.get("error")}, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)
    if 400 <= resp.status_code < 500:
        return AssuranceResult.pass_result(
            name, AUTH_CATEGORY,
            f"Server rejected the invalid version header (HTTP "
            f"{resp.status_code})",
            {"status_code": resp.status_code}, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)
    if isinstance(json_body, dict) and "result" in json_body:
        result = json_body["result"]
        negotiated = (
            result.get("protocolVersion") if isinstance(result, dict) else None
        )
        if negotiated == "0.0.0":
            return AssuranceResult.warn_result(
                name, AUTH_CATEGORY,
                "Server accepted the invalid version '0.0.0' unchanged",
                {"protocolVersion": negotiated}, "medium",
                conformance_level="SHOULD", spec_clause=spec_clause)
        if isinstance(negotiated, str) and negotiated:
            return AssuranceResult.pass_result(
                name, AUTH_CATEGORY,
                f"Server negotiated supported protocol version '{negotiated}' "
                f"despite the invalid '0.0.0' header",
                {"protocolVersion": negotiated}, "medium",
                conformance_level="SHOULD", spec_clause=spec_clause)
        return AssuranceResult.warn_result(
            name, AUTH_CATEGORY,
            "Server returned a result without a protocolVersion to verify "
            "negotiation",
            {"result": result}, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)
    return AssuranceResult.warn_result(
        name, AUTH_CATEGORY,
        "Server returned a malformed response to the invalid version header",
        {"status_code": resp.status_code, "body": json_body}, "medium",
        conformance_level="SHOULD", spec_clause=spec_clause)


def run_oauth_discovery_endpoint_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    """SHOULD: GET /.well-known/oauth-authorization-server should return an
    OAuth 2.1 authorization-server metadata document (issuer +
    authorization_endpoint). A 404 is an advisory WARN (many MCP servers do not
    require auth); only malformed JSON or a 5xx is a FAIL. HTTP transport
    only."""
    name = "OAuth Discovery Endpoint"
    spec_clause = (
        "MCP spec 2025-11-25 §6.3 — OAuth 2.1 authorization server metadata"
    )

    server_url = _http_server_url(client)
    if server_url is None:
        return AssuranceResult.skip_result(
            name, AUTH_CATEGORY,
            "OAuth discovery applies to HTTP transport only",
            conformance_level="SHOULD", spec_clause=spec_clause)

    url = _http_origin(server_url) + "/.well-known/oauth-authorization-server"
    try:
        resp = requests.get(url, timeout=getattr(client, "timeout", 5),
                            headers={"Accept": "application/json"})
    except requests.RequestException as exc:
        return AssuranceResult.fail_result(
            name, AUTH_CATEGORY,
            f"Transport error fetching OAuth discovery document: {exc}",
            {"transport_error": str(exc)}, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)

    if resp.status_code == 404:
        return AssuranceResult.warn_result(
            name, AUTH_CATEGORY,
            "OAuth discovery endpoint not implemented (404) — advisory; not "
            "all MCP servers require authorization",
            {"status_code": 404}, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)
    if resp.status_code >= 500:
        return AssuranceResult.fail_result(
            name, AUTH_CATEGORY,
            f"OAuth discovery endpoint returned a server error "
            f"(HTTP {resp.status_code})",
            {"status_code": resp.status_code}, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)

    body, ok = _parse_response_json(resp)
    if not ok or not isinstance(body, dict):
        return AssuranceResult.fail_result(
            name, AUTH_CATEGORY,
            "OAuth discovery endpoint returned malformed JSON",
            {"status_code": resp.status_code, "text": (resp.text or "")[:200]},
            "medium", conformance_level="SHOULD", spec_clause=spec_clause)
    if "issuer" in body and "authorization_endpoint" in body:
        return AssuranceResult.pass_result(
            name, AUTH_CATEGORY,
            "OAuth discovery document present with issuer and "
            "authorization_endpoint",
            {"issuer": body.get("issuer"),
             "authorization_endpoint": body.get("authorization_endpoint")},
            "medium", conformance_level="SHOULD", spec_clause=spec_clause)
    return AssuranceResult.warn_result(
        name, AUTH_CATEGORY,
        "OAuth discovery document is missing issuer or authorization_endpoint",
        {"keys": sorted(body.keys())}, "medium",
        conformance_level="SHOULD", spec_clause=spec_clause)


def run_unauthenticated_request_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    """SHOULD: an initialize sent with no Authorization header should yield
    either a 401 carrying WWW-Authenticate (protected) or a 200 with a valid
    JSON-RPC result (open/public). A 401 without WWW-Authenticate is an
    advisory WARN; a 5xx/crash is a FAIL. HTTP transport only."""
    name = "Unauthenticated Request Response"
    spec_clause = (
        "MCP spec 2025-11-25 §6.3 — 401 with WWW-Authenticate on protected "
        "resources"
    )

    server_url = _http_server_url(client)
    if server_url is None:
        return AssuranceResult.skip_result(
            name, AUTH_CATEGORY,
            "Authorization handling applies to HTTP transport only",
            conformance_level="SHOULD", spec_clause=spec_clause)

    body = _valid_initialize_body(protocol_version, "auth-no-authorization")
    try:
        # Deliberately send NO Authorization header.
        resp = requests.post(
            server_url, json=body, timeout=getattr(client, "timeout", 5),
            headers={"Accept": "application/json",
                     "Content-Type": "application/json"},
        )
    except requests.RequestException as exc:
        return AssuranceResult.fail_result(
            name, AUTH_CATEGORY,
            f"Transport error on unauthenticated request: {exc}",
            {"transport_error": str(exc)}, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)

    if resp.status_code >= 500:
        return AssuranceResult.fail_result(
            name, AUTH_CATEGORY,
            f"Server returned a server error to an unauthenticated request "
            f"(HTTP {resp.status_code})",
            {"status_code": resp.status_code}, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)

    if resp.status_code == 401:
        if resp.headers.get("WWW-Authenticate"):
            return AssuranceResult.pass_result(
                name, AUTH_CATEGORY,
                "Server returned 401 with a WWW-Authenticate header "
                "(protected resource)",
                {"status_code": 401,
                 "www_authenticate": resp.headers.get("WWW-Authenticate")},
                "medium", conformance_level="SHOULD", spec_clause=spec_clause)
        return AssuranceResult.warn_result(
            name, AUTH_CATEGORY,
            "Server returned 401 but no WWW-Authenticate header "
            "(incomplete auth response)",
            {"status_code": 401}, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)

    json_body, _ = _parse_response_json(resp)
    if 200 <= resp.status_code < 300 and isinstance(json_body, dict) \
            and "result" in json_body:
        return AssuranceResult.pass_result(
            name, AUTH_CATEGORY,
            "Server is open/public: responded 200 with a valid JSON-RPC "
            "result to an unauthenticated request",
            {"status_code": resp.status_code}, "medium",
            conformance_level="SHOULD", spec_clause=spec_clause)
    return AssuranceResult.warn_result(
        name, AUTH_CATEGORY,
        "Server returned an unexpected response to an unauthenticated request",
        {"status_code": resp.status_code, "body": json_body}, "medium",
        conformance_level="SHOULD", spec_clause=spec_clause)


def run_transport_version_header_response_test(
    client: BaseMCPClient,
    protocol_version: str,
) -> AssuranceResult:
    """MUST: a normal initialize should produce an HTTP response that echoes
    the MCP-Protocol-Version header. The MUST is that the transport stays
    functional; an absent header is an advisory WARN. HTTP transport only."""
    name = "Transport Version Header in Response"
    spec_clause = "MCP spec 2025-11-25 §2.4 — MCP-Protocol-Version in responses"

    server_url = _http_server_url(client)
    if server_url is None:
        return AssuranceResult.skip_result(
            name, AUTH_CATEGORY,
            "Response version header applies to HTTP transport only",
            conformance_level="MUST", spec_clause=spec_clause)

    body = _valid_initialize_body(protocol_version, "auth-version-echo")
    try:
        resp = requests.post(
            server_url, json=body, timeout=getattr(client, "timeout", 5),
            headers={"Accept": "application/json",
                     "Content-Type": "application/json",
                     "MCP-Protocol-Version": protocol_version},
        )
    except requests.RequestException as exc:
        return AssuranceResult.fail_result(
            name, AUTH_CATEGORY,
            f"Transport error checking response version header: {exc}",
            {"transport_error": str(exc)}, "high",
            conformance_level="MUST", spec_clause=spec_clause)

    echoed = resp.headers.get("MCP-Protocol-Version")
    if echoed:
        return AssuranceResult.pass_result(
            name, AUTH_CATEGORY,
            "Response contains the MCP-Protocol-Version header",
            {"MCP-Protocol-Version": echoed}, "high",
            conformance_level="MUST", spec_clause=spec_clause)
    return AssuranceResult.warn_result(
        name, AUTH_CATEGORY,
        "Response did not include the MCP-Protocol-Version header "
        "(advisory — server should echo it back)",
        {"status_code": resp.status_code}, "high",
        conformance_level="MUST", spec_clause=spec_clause)


DEFAULT_CASES = [
    AssuranceCase(
        "Initialize Handshake",
        "Protocol Conformance",
        "critical",
        run_initialize_test,
        conformance_level="MUST",
        spec_clause="MCP spec 2025-11-25 §3.1 — initialize lifecycle",
    ),
    AssuranceCase(
        "Initialized Notification",
        "Protocol Conformance",
        "high",
        run_initialized_notification_test,
        conformance_level="MUST",
        spec_clause="MCP spec 2025-11-25 §3.1 — notifications/initialized",
    ),
    AssuranceCase(
        "Tools List Schema",
        "Functional Correctness",
        "high",
        run_tools_list_test,
        conformance_level="MUST",
        spec_clause="MCP spec 2025-11-25 §5.1 — tools/list response shape",
    ),
    AssuranceCase(
        "Resources List Schema",
        "Functional Correctness",
        "medium",
        run_resources_list_test,
        conformance_level="MUST",
        spec_clause="MCP spec 2025-11-25 §5.2 — resources/list response shape",
    ),
    AssuranceCase(
        "Prompts List Schema",
        "Functional Correctness",
        "medium",
        run_prompts_list_test,
        conformance_level="MUST",
        spec_clause="MCP spec 2025-11-25 §5.3 — prompts/list response shape",
    ),
    AssuranceCase(
        "Resource Read Validation",
        "Functional Correctness",
        "medium",
        run_resources_read_test,
        conformance_level="MUST",
        spec_clause="MCP spec 2025-11-25 §5.2 — resources/read response",
    ),
    AssuranceCase(
        "Prompt Get Validation",
        "Functional Correctness",
        "medium",
        run_prompts_get_test,
        conformance_level="MUST",
        spec_clause="MCP spec 2025-11-25 §5.3 — prompts/get response",
    ),
    AssuranceCase(
        "Advertised Tool Execution",
        "Functional Correctness",
        "high",
        run_calculator_tool_test,
        conformance_level="MUST",
        spec_clause="MCP spec 2025-11-25 §5.1 — tools/call response",
    ),
    AssuranceCase(
        "Unknown Method Rejection",
        "Protocol Conformance",
        "high",
        run_unknown_method_test,
        conformance_level="MUST",
        spec_clause="JSON-RPC 2.0 §5.1 — method not found (-32601)",
    ),
    AssuranceCase(
        "Null Method Rejection",
        "Basic Security Validation",
        "high",
        run_null_method_test,
        conformance_level="MUST",
        spec_clause="JSON-RPC 2.0 §4 — method must be non-null string",
    ),
    AssuranceCase(
        "Invalid Method Type Rejection",
        "Basic Security Validation",
        "high",
        run_invalid_method_type_test,
        conformance_level="MUST",
        spec_clause="JSON-RPC 2.0 §4 — method must be string",
    ),
    AssuranceCase(
        "Empty Method Rejection",
        "Basic Security Validation",
        "high",
        run_empty_method_test,
        conformance_level="MUST",
        spec_clause="JSON-RPC 2.0 §4 — method must be non-empty",
    ),
    AssuranceCase(
        "Missing JSON-RPC Version Rejection",
        "Basic Security Validation",
        "high",
        run_missing_jsonrpc_test,
        conformance_level="MUST",
        spec_clause="JSON-RPC 2.0 §4 — jsonrpc field required",
    ),
    AssuranceCase(
        "Invalid JSON-RPC Version Rejection",
        "Basic Security Validation",
        "high",
        run_invalid_jsonrpc_version_test,
        conformance_level="MUST",
        spec_clause="JSON-RPC 2.0 §4 — jsonrpc must be exactly 2.0",
    ),
    AssuranceCase(
        "Malformed JSON Parse Error",
        "Advanced Negative Validation",
        "high",
        run_malformed_json_test,
        conformance_level="MUST",
        spec_clause="JSON-RPC 2.0 §4.1 — parse error (-32700)",
    ),
    AssuranceCase(
        "Non-Object JSON Rejection",
        "Advanced Negative Validation",
        "high",
        run_non_object_json_test,
        conformance_level="MUST",
        spec_clause="JSON-RPC 2.0 §4 — request must be object",
    ),
    AssuranceCase(
        "Missing Method Field Rejection",
        "Advanced Negative Validation",
        "high",
        run_missing_method_test,
        conformance_level="MUST",
        spec_clause="JSON-RPC 2.0 §4 — method field required",
    ),
    AssuranceCase(
        "Missing Id Treated as Notification",
        "Protocol Conformance",
        "high",
        run_missing_request_id_test,
        conformance_level="MUST",
        spec_clause="JSON-RPC 2.0 §4 — no-id message is notification",
    ),
    AssuranceCase(
        "Null Id Treated as Notification",
        "Protocol Conformance",
        "high",
        run_null_request_id_test,
        conformance_level="MUST",
        spec_clause="JSON-RPC 2.0 §4 — null-id message is notification",
    ),
    AssuranceCase(
        "Array Params Rejection",
        "Advanced Negative Validation",
        "high",
        run_params_array_test,
        conformance_level="MUST",
        spec_clause="JSON-RPC 2.0 §4 — params must be object not array",
    ),
    AssuranceCase(
        "Unsupported Protocol Version Handling",
        "Advanced Negative Validation",
        "high",
        run_unsupported_protocol_version_test,
        conformance_level="SHOULD",
        spec_clause="MCP spec 2025-11-25 §3.1 — version negotiation",
    ),
    AssuranceCase(
        "Missing Initialize Client Info Rejection",
        "Advanced Negative Validation",
        "high",
        run_missing_initialize_client_info_test,
        conformance_level="SHOULD",
        spec_clause="MCP spec 2025-11-25 §3.1 — clientInfo field",
    ),
    AssuranceCase(
        "Invalid Tool Parameters Rejection",
        "Advanced Negative Validation",
        "high",
        run_invalid_tool_parameters_test,
        conformance_level="SHOULD",
        spec_clause="MCP spec 2025-11-25 §5.1 — parameter validation",
    ),
    AssuranceCase(
        "String Request Id Echo",
        "Interoperability",
        "medium",
        run_string_request_id_echo_test,
        conformance_level="MUST",
        spec_clause="JSON-RPC 2.0 §4 — id must be echoed in response",
    ),
    AssuranceCase(
        "Declared Capability Consistency",
        "Interoperability",
        "medium",
        run_capability_consistency_test,
        conformance_level="MUST",
        spec_clause="MCP spec 2025-11-25 §3.2 — capability negotiation",
    ),
    AssuranceCase(
        "Pagination Cursor Handling",
        "Protocol Conformance",
        "medium",
        run_pagination_cursor_test,
        conformance_level="SHOULD",
        spec_clause="MCP spec 2025-11-25 §5 — pagination cursor",
    ),
    AssuranceCase(
        "Capability-Gated Tool Call",
        "Functional Correctness",
        "high",
        run_capability_gated_tool_call_test,
        conformance_level="MUST",
        spec_clause="MCP spec 2025-11-25 §3.2 — strict capability gating",
    ),
    AssuranceCase(
        "Tools List Next Cursor",
        "Protocol Conformance",
        "medium",
        run_tools_list_next_cursor_test,
        conformance_level="SHOULD",
        spec_clause="MCP spec 2025-11-25 §5 — nextCursor in list responses",
    ),
    AssuranceCase(
        "Server Info Completeness",
        "Protocol Conformance",
        "medium",
        run_server_info_completeness_test,
        conformance_level="SHOULD",
        spec_clause="MCP spec 2025-11-25 §3.1 — serverInfo fields",
    ),
    AssuranceCase(
        "Protocol Version Header Enforcement",
        AUTH_CATEGORY,
        "high",
        run_protocol_version_header_required_test,
        conformance_level="MUST",
        spec_clause="MCP spec 2025-11-25 §2.4 — MCP-Protocol-Version header required",
    ),
    AssuranceCase(
        "Invalid Protocol Version Header Handling",
        AUTH_CATEGORY,
        "medium",
        run_invalid_protocol_version_header_test,
        conformance_level="SHOULD",
        spec_clause="MCP spec 2025-11-25 §2.4 — version header validation",
    ),
    AssuranceCase(
        "OAuth Discovery Endpoint",
        AUTH_CATEGORY,
        "medium",
        run_oauth_discovery_endpoint_test,
        conformance_level="SHOULD",
        spec_clause="MCP spec 2025-11-25 §6.3 — OAuth 2.1 authorization server metadata",
    ),
    AssuranceCase(
        "Unauthenticated Request Response",
        AUTH_CATEGORY,
        "medium",
        run_unauthenticated_request_test,
        conformance_level="SHOULD",
        spec_clause="MCP spec 2025-11-25 §6.3 — 401 with WWW-Authenticate on protected resources",
    ),
    AssuranceCase(
        "Transport Version Header in Response",
        AUTH_CATEGORY,
        "high",
        run_transport_version_header_response_test,
        conformance_level="MUST",
        spec_clause="MCP spec 2025-11-25 §2.4 — MCP-Protocol-Version in responses",
    ),
]


def _is_server_terminated(result: AssuranceResult) -> bool:
    """Check whether a test result indicates the STDIO server process died."""
    termination_indicators = (
        "STDIO process is not running",
        "STDIO write failed",
    )
    if result.status != "FAIL":
        return False
    message = result.message or ""
    evidence_error = str(result.evidence.get("transport_error", ""))
    combined = f"{message} {evidence_error}"
    return any(indicator in combined for indicator in termination_indicators)


def run_suite(
    client: BaseMCPClient,
    protocol_version: str,
    cases: list[AssuranceCase] | None = None,
) -> list[AssuranceResult]:
    results = []
    server_terminated = False
    triggering_test = None

    for case in cases or DEFAULT_CASES:
        if server_terminated:
            results.append(
                AssuranceResult.skip_result(
                    case.name,
                    case.category,
                    f"Skipped: STDIO server terminated during "
                    f"'{triggering_test}'",
                    conformance_level=case.conformance_level,
                    spec_clause=case.spec_clause,
                )
            )
            continue

        try:
            result = case.runner(client, protocol_version)
        except Exception as exc:
            result = AssuranceResult.fail_result(
                case.name,
                case.category,
                f"Unhandled test exception: {exc}",
                severity=case.severity,
            )

        terminated_now = _is_server_terminated(result)
        if terminated_now:
            server_terminated = True
            triggering_test = case.name
            result = AssuranceResult.fail_result(
                case.name,
                case.category,
                f"STDIO server process terminated unexpectedly "
                f"(original: {result.message})",
                evidence={"server_terminated": True},
                severity="critical",
            )

        # Stamp spec-conformance metadata from the case onto every result so
        # the reporter can tag and group by normative level uniformly.
        result.conformance_level = case.conformance_level
        result.spec_clause = case.spec_clause

        # A failed SHOULD-level expectation is an advisory (WARN), not a hard
        # MUST violation (FAIL) — unless the failure is a server termination.
        if (
            not terminated_now
            and case.conformance_level == "SHOULD"
            and result.status == "FAIL"
        ):
            result = AssuranceResult.warn_result(
                result.test,
                result.category,
                result.message,
                result.evidence,
                result.severity,
                conformance_level=case.conformance_level,
                spec_clause=case.spec_clause,
            )

        results.append(result)

    return results
