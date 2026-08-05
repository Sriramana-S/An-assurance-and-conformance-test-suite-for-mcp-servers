import pytest

from core.suite import (
    run_capability_consistency_test,
    run_string_request_id_echo_test,
)


def run_and_assert(result):
    if result.status == "SKIP":
        pytest.skip(result.message)
    assert result.status == "PASS", result.message


def test_string_request_id_echo(client, protocol_version):
    run_and_assert(run_string_request_id_echo_test(client, protocol_version))


def test_declared_capability_consistency(client, protocol_version):
    run_and_assert(run_capability_consistency_test(client, protocol_version))
