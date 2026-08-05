from core.suite import (
    run_invalid_tool_parameters_test,
    run_malformed_json_test,
    run_missing_initialize_client_info_test,
    run_missing_method_test,
    run_missing_request_id_test,
    run_non_object_json_test,
    run_null_request_id_test,
    run_params_array_test,
    run_unsupported_protocol_version_test,
)


def run_and_assert(result):
    assert result.status == "PASS", result.message


def test_malformed_json_returns_parse_error(client, protocol_version):
    run_and_assert(run_malformed_json_test(client, protocol_version))


def test_non_object_json_is_rejected(client, protocol_version):
    run_and_assert(run_non_object_json_test(client, protocol_version))


def test_missing_method_field_is_rejected(client, protocol_version):
    run_and_assert(run_missing_method_test(client, protocol_version))


def test_missing_request_id_treated_as_notification(client, protocol_version):
    # A no-id message is a JSON-RPC notification: the server must stay
    # silent. The runner returns PASS on silence/empty body and FAIL on
    # any unexpected error or success response.
    run_and_assert(run_missing_request_id_test(client, protocol_version))


def test_null_request_id_treated_as_notification(client, protocol_version):
    # A null-id message is likewise a notification; server silence is
    # the only correct behaviour.
    run_and_assert(run_null_request_id_test(client, protocol_version))


def test_array_params_are_rejected(client, protocol_version):
    run_and_assert(run_params_array_test(client, protocol_version))


def test_unsupported_protocol_version_handled(client, protocol_version):
    run_and_assert(run_unsupported_protocol_version_test(client, protocol_version))


def test_missing_initialize_client_info_is_rejected(client, protocol_version):
    run_and_assert(run_missing_initialize_client_info_test(client, protocol_version))


def test_invalid_tool_parameters_are_rejected(client, protocol_version):
    run_and_assert(run_invalid_tool_parameters_test(client, protocol_version))
