from core.suite import (
    run_empty_method_test,
    run_initialize_test,
    run_initialized_notification_test,
    run_invalid_jsonrpc_version_test,
    run_missing_jsonrpc_test,
    run_unknown_method_test,
)


def run_and_assert(result):
    assert result.status == "PASS", result.message


def test_initialize_handshake(client, protocol_version):
    run_and_assert(run_initialize_test(client, protocol_version))


def test_initialized_notification(client, protocol_version):
    run_and_assert(run_initialized_notification_test(client, protocol_version))


def test_unknown_method_rejected(client, protocol_version):
    run_and_assert(run_unknown_method_test(client, protocol_version))


def test_missing_jsonrpc_rejected(client, protocol_version):
    run_and_assert(run_missing_jsonrpc_test(client, protocol_version))


def test_invalid_jsonrpc_version_rejected(client, protocol_version):
    run_and_assert(run_invalid_jsonrpc_version_test(client, protocol_version))


def test_empty_method_rejected(client, protocol_version):
    run_and_assert(run_empty_method_test(client, protocol_version))
