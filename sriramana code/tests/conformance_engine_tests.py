from core.conformance import (
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    ProtocolConformanceEngine,
)
from core.models import ClientResponse
from core.suite import initialize_params, notification_payload, request_payload


def ok_response(request_id, result=None):
    return ClientResponse(
        status_code=200,
        body={
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result or {},
        },
    )


def error_response(request_id, code):
    return ClientResponse(
        status_code=200,
        body={
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": "error",
            },
        },
    )


def initialize_response(request_id):
    return ok_response(
        request_id,
        {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "serverInfo": {
                "name": "sample",
                "version": "1.0.0",
            },
        },
    )


def test_request_structure_requires_non_null_string_or_integer_id():
    engine = ProtocolConformanceEngine()
    payload = request_payload("initialize", initialize_params("2025-11-25"), None)

    result = engine.validate_request(payload)

    assert not result.passed
    assert "id" in result.message


def test_duplicate_request_ids_are_rejected_within_session():
    engine = ProtocolConformanceEngine()
    first = request_payload("initialize", initialize_params("2025-11-25"), 1)
    second = request_payload("initialize", initialize_params("2025-11-25"), 1)

    assert engine.validate_request(first).passed
    result = engine.validate_request(second)

    assert not result.passed
    assert "already been used" in result.message


def test_response_id_must_match_pending_request():
    engine = ProtocolConformanceEngine()
    request = request_payload("initialize", initialize_params("2025-11-25"), 1)
    engine.validate_request(request)

    result = engine.validate_response(initialize_response(2), expected_id=1)

    assert not result.passed
    assert "does not match" in result.message


def test_error_code_must_match_expected_code():
    engine = ProtocolConformanceEngine()
    request = request_payload("initialize", initialize_params("2025-11-25"), 1)
    engine.validate_request(request)

    result = engine.validate_response(
        error_response(1, METHOD_NOT_FOUND),
        expected_id=1,
        expected_error_code=INVALID_REQUEST,
        require_result=False,
    )

    assert not result.passed
    assert result.details["expected_code"] == INVALID_REQUEST
    assert result.details["actual_code"] == METHOD_NOT_FOUND


def test_lifecycle_rejects_operation_before_initialize():
    engine = ProtocolConformanceEngine()
    request = request_payload("tools/list", {}, 1)

    result = engine.validate_request(request)

    assert not result.passed
    assert "Initialization" in result.message


def test_lifecycle_requires_initialized_notification_before_operation():
    engine = ProtocolConformanceEngine()
    initialize = request_payload("initialize", initialize_params("2025-11-25"), 1)
    tools = request_payload("tools/list", {}, 2)

    assert engine.validate_request(initialize).passed
    assert engine.validate_response(initialize_response(1), expected_id=1).passed

    blocked = engine.validate_request(tools)
    assert not blocked.passed
    assert "notifications/initialized" in blocked.message

    notification = notification_payload("notifications/initialized")
    assert engine.validate_notification(notification).passed
    assert engine.validate_request(tools).passed
