from core.models import ClientResponse, ValidationResult
from core.conformance import ProtocolConformanceEngine


class ProtocolValidator:

    @staticmethod
    def validate_jsonrpc(
        response: ClientResponse,
        expected_id=None,
        require_result=None,
        engine: ProtocolConformanceEngine | None = None,
    ) -> ValidationResult:
        conformance = engine or ProtocolConformanceEngine()
        return conformance.validate_response(
            response,
            expected_id=expected_id,
            require_result=require_result,
        )

    @staticmethod
    def validate_error_object(error) -> ValidationResult:
        return ProtocolConformanceEngine().validate_error_object(error)

    @staticmethod
    def validate_error_response(
        response: ClientResponse,
        expected_code: int | None = None,
        expected_id=None,
        engine: ProtocolConformanceEngine | None = None,
    ) -> ValidationResult:
        conformance = engine or ProtocolConformanceEngine()
        return conformance.validate_response(
            response,
            expected_id=expected_id,
            expected_error_code=expected_code,
            require_result=False,
        )

    @staticmethod
    def validate_initialize_response(
        response: ClientResponse,
        expected_id=None,
        engine: ProtocolConformanceEngine | None = None,
    ) -> ValidationResult:
        base = ProtocolValidator.validate_jsonrpc(
            response,
            expected_id=expected_id,
            require_result=True,
            engine=engine,
        )
        if not base.passed:
            return base

        result = response.body["result"]
        if not isinstance(result, dict):
            return ValidationResult(False, "Initialize result is not an object")

        required_fields = ["protocolVersion", "capabilities", "serverInfo"]
        for field in required_fields:
            if field not in result:
                return ValidationResult(False, f"Initialize result missing {field}")

        if not isinstance(result["protocolVersion"], str):
            return ValidationResult(False, "protocolVersion must be a string")

        if not isinstance(result["capabilities"], dict):
            return ValidationResult(False, "capabilities must be an object")

        server_info = result["serverInfo"]
        if not isinstance(server_info, dict):
            return ValidationResult(False, "serverInfo must be an object")

        if not isinstance(server_info.get("name"), str) or not server_info["name"]:
            return ValidationResult(False, "serverInfo.name is missing or empty")

        if not isinstance(server_info.get("version"), str):
            return ValidationResult(False, "serverInfo.version is missing")

        return ValidationResult(
            True,
            "Initialize response has protocol, capabilities and server metadata",
            {"protocolVersion": result["protocolVersion"]},
        )

    @staticmethod
    def validate_tools_list(
        response: ClientResponse,
        expected_id=None,
        engine: ProtocolConformanceEngine | None = None,
    ):
        base = ProtocolValidator.validate_jsonrpc(
            response,
            expected_id=expected_id,
            require_result=True,
            engine=engine,
        )
        if not base.passed:
            return base

        tools = response.body["result"].get("tools")
        if not isinstance(tools, list):
            return ValidationResult(False, "tools/list result missing tools array")

        for index, tool in enumerate(tools):
            if not isinstance(tool, dict):
                return ValidationResult(False, f"Tool {index} is not an object")
            if not isinstance(tool.get("name"), str) or not tool["name"]:
                return ValidationResult(False, f"Tool {index} has invalid name")
            input_schema = tool.get("inputSchema")
            if not isinstance(input_schema, dict):
                return ValidationResult(
                    False,
                    f"Tool {tool['name']} missing inputSchema object",
                )

        return ValidationResult(
            True,
            f"tools/list returned {len(tools)} valid tool definitions",
            {"tool_count": len(tools)},
        )

    @staticmethod
    def validate_resources_list(
        response: ClientResponse,
        expected_id=None,
        engine: ProtocolConformanceEngine | None = None,
    ):
        base = ProtocolValidator.validate_jsonrpc(
            response,
            expected_id=expected_id,
            require_result=True,
            engine=engine,
        )
        if not base.passed:
            return base

        resources = response.body["result"].get("resources")
        if not isinstance(resources, list):
            return ValidationResult(
                False,
                "resources/list result missing resources array",
            )

        for index, resource in enumerate(resources):
            if not isinstance(resource, dict):
                return ValidationResult(False, f"Resource {index} is not an object")
            if not isinstance(resource.get("uri"), str) or not resource["uri"]:
                return ValidationResult(False, f"Resource {index} has invalid uri")
            if not isinstance(resource.get("name"), str) or not resource["name"]:
                return ValidationResult(False, f"Resource {index} has invalid name")

        return ValidationResult(
            True,
            f"resources/list returned {len(resources)} valid resource definitions",
            {"resource_count": len(resources)},
        )

    @staticmethod
    def validate_prompts_list(
        response: ClientResponse,
        expected_id=None,
        engine: ProtocolConformanceEngine | None = None,
    ):
        base = ProtocolValidator.validate_jsonrpc(
            response,
            expected_id=expected_id,
            require_result=True,
            engine=engine,
        )
        if not base.passed:
            return base

        prompts = response.body["result"].get("prompts")
        if not isinstance(prompts, list):
            return ValidationResult(False, "prompts/list result missing prompts array")

        for index, prompt in enumerate(prompts):
            if not isinstance(prompt, dict):
                return ValidationResult(False, f"Prompt {index} is not an object")
            if not isinstance(prompt.get("name"), str) or not prompt["name"]:
                return ValidationResult(False, f"Prompt {index} has invalid name")
            arguments = prompt.get("arguments", [])
            if arguments is not None and not isinstance(arguments, list):
                return ValidationResult(
                    False,
                    f"Prompt {prompt['name']} arguments must be an array",
                )

        return ValidationResult(
            True,
            f"prompts/list returned {len(prompts)} valid prompt definitions",
            {"prompt_count": len(prompts)},
        )

    @staticmethod
    def validate_tool_call(
        response: ClientResponse,
        expected_id=None,
        engine: ProtocolConformanceEngine | None = None,
    ):
        base = ProtocolValidator.validate_jsonrpc(
            response,
            expected_id=expected_id,
            require_result=True,
            engine=engine,
        )
        if not base.passed:
            return base

        result = response.body["result"]
        if not isinstance(result, dict):
            return ValidationResult(False, "tools/call result is not an object")

        content = result.get("content")
        if not isinstance(content, list):
            return ValidationResult(False, "tools/call result missing content array")

        if result.get("isError") is True:
            return ValidationResult(False, "tools/call returned isError=true")

        return ValidationResult(True, "Advertised tool executed successfully")

    @staticmethod
    def validate_resource_read(
        response: ClientResponse,
        expected_id=None,
        engine: ProtocolConformanceEngine | None = None,
    ):
        base = ProtocolValidator.validate_jsonrpc(
            response,
            expected_id=expected_id,
            require_result=True,
            engine=engine,
        )
        if not base.passed:
            return base

        result = response.body["result"]
        if not isinstance(result, dict):
            return ValidationResult(False, "resources/read result is not an object")

        contents = result.get("contents")
        if not isinstance(contents, list):
            return ValidationResult(
                False,
                "resources/read result missing contents array",
            )

        for index, item in enumerate(contents):
            if not isinstance(item, dict):
                return ValidationResult(False, f"Content {index} is not an object")
            if not isinstance(item.get("uri"), str) or not item["uri"]:
                return ValidationResult(
                    False,
                    f"Content {index} has invalid or missing uri",
                )
            if "text" not in item and "blob" not in item:
                return ValidationResult(
                    False,
                    f"Content {index} must contain either text or blob representation",
                )
            if "text" in item and not isinstance(item["text"], str):
                return ValidationResult(False, f"Content {index} text must be a string")
            if "blob" in item and not isinstance(item["blob"], str):
                return ValidationResult(False, f"Content {index} blob must be a string")

        return ValidationResult(
            True,
            f"resources/read returned {len(contents)} valid resource content entries",
            {"content_count": len(contents)},
        )

    @staticmethod
    def validate_prompt_get(
        response: ClientResponse,
        expected_id=None,
        engine: ProtocolConformanceEngine | None = None,
    ):
        base = ProtocolValidator.validate_jsonrpc(
            response,
            expected_id=expected_id,
            require_result=True,
            engine=engine,
        )
        if not base.passed:
            return base

        result = response.body["result"]
        if not isinstance(result, dict):
            return ValidationResult(False, "prompts/get result is not an object")

        messages = result.get("messages")
        if not isinstance(messages, list):
            return ValidationResult(False, "prompts/get result missing messages array")

        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                return ValidationResult(False, f"Message {index} is not an object")
            if not isinstance(message.get("role"), str) or not message["role"]:
                return ValidationResult(
                    False,
                    f"Message {index} has invalid or missing role",
                )
            content = message.get("content")
            if not isinstance(content, dict):
                return ValidationResult(
                    False,
                    f"Message {index} content is not an object",
                )
            if not isinstance(content.get("type"), str) or not content["type"]:
                return ValidationResult(
                    False,
                    f"Message {index} content type is missing or invalid",
                )

        return ValidationResult(
            True,
            f"prompts/get returned {len(messages)} valid prompt messages",
            {"message_count": len(messages)},
        )
