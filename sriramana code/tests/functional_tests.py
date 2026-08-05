import pytest

from core.suite import (
    run_calculator_tool_test,
    run_prompts_list_test,
    run_resources_list_test,
    run_tools_list_test,
    run_resources_read_test,
    run_prompts_get_test,
)


def run_and_assert(result):
    if result.status == "SKIP":
        pytest.skip(result.message)
    assert result.status == "PASS", result.message


def test_tools_list_schema(client, protocol_version):
    run_and_assert(run_tools_list_test(client, protocol_version))


def test_resources_list_schema(client, protocol_version):
    run_and_assert(run_resources_list_test(client, protocol_version))


def test_resources_read_schema(client, protocol_version):
    run_and_assert(run_resources_read_test(client, protocol_version))


def test_prompts_list_schema(client, protocol_version):
    run_and_assert(run_prompts_list_test(client, protocol_version))


def test_prompts_get_schema(client, protocol_version):
    run_and_assert(run_prompts_get_test(client, protocol_version))


def test_advertised_tool_execution(client, protocol_version):
    run_and_assert(run_calculator_tool_test(client, protocol_version))
