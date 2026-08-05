from core.suite import (
    run_invalid_method_type_test,
    run_null_method_test,
)


def run_and_assert(result):
    assert result.status == "PASS", result.message


def test_null_method_rejected(client, protocol_version):
    run_and_assert(run_null_method_test(client, protocol_version))


def test_invalid_method_type_rejected(client, protocol_version):
    run_and_assert(run_invalid_method_type_test(client, protocol_version))
