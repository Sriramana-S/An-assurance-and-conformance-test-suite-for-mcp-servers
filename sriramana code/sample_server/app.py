import json
from json import JSONDecodeError

from flask import Flask, jsonify, request


app = Flask(__name__)

PROTOCOL_VERSION = "2025-11-25"


def success_response(request_id, result):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }


def error_response(request_id, code, message):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


def parse_error():
    return error_response(None, -32700, "Parse error")


def invalid_request(request_id, message="Invalid Request"):
    return error_response(request_id, -32600, message)


def invalid_params(request_id, message="Invalid params"):
    return error_response(request_id, -32602, message)


def method_not_found(request_id, method):
    return error_response(request_id, -32601, f"Method not found: {method}")


def list_tools():
    return {
        "tools": [
            {
                "name": "calculator",
                "title": "Calculator",
                "description": "Performs basic arithmetic operations.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["add", "subtract", "multiply", "divide"],
                        },
                        "a": {"type": "number"},
                        "b": {"type": "number"},
                    },
                    "required": ["operation", "a", "b"],
                },
            },
            {
                "name": "echo",
                "title": "Echo",
                "description": "Returns a text value supplied by the client.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                    },
                    "required": ["text"],
                },
            },
        ]
    }


def list_resources():
    return {
        "resources": [
            {
                "uri": "file:///demo/compliance-policy.md",
                "name": "compliance-policy",
                "title": "Compliance Policy",
                "description": "Synthetic policy resource used for assurance testing.",
                "mimeType": "text/markdown",
            },
            {
                "uri": "file:///demo/test-data.json",
                "name": "test-data",
                "title": "Synthetic Test Data",
                "description": "Small JSON fixture for local protocol checks.",
                "mimeType": "application/json",
            },
        ]
    }


def list_prompts():
    return {
        "prompts": [
            {
                "name": "summarise_assurance_result",
                "title": "Summarise Assurance Result",
                "description": "Summarises an assurance finding for a developer.",
                "arguments": [
                    {
                        "name": "finding",
                        "description": "The assurance finding to summarise.",
                        "required": True,
                    }
                ],
            }
        ]
    }


def read_resource(params):
    if not isinstance(params, dict):
        return invalid_params(None, "resources/read params must be an object")

    uri = params.get("uri")
    if not isinstance(uri, str) or not uri:
        return invalid_params(None, "resources/read uri must be a non-empty string")

    if uri == "file:///demo/compliance-policy.md":
        content = "# Compliance Policy\n\nThis is synthetic policy content for assurance testing."
        mime_type = "text/markdown"
    elif uri == "file:///demo/test-data.json":
        content = '{"status": "compliant", "checked": true}'
        mime_type = "application/json"
    else:
        return error_response(None, -32602, f"Resource not found: {uri}")

    return {
        "contents": [
            {
                "uri": uri,
                "mimeType": mime_type,
                "text": content,
            }
        ]
    }


def get_prompt(params):
    if not isinstance(params, dict):
        return invalid_params(None, "prompts/get params must be an object")

    name = params.get("name")
    arguments = params.get("arguments", {})
    if not isinstance(name, str) or not name:
        return invalid_params(None, "prompts/get name must be a non-empty string")

    if name == "summarise_assurance_result":
        finding = arguments.get("finding", "no finding provided")
        return {
            "description": "Summarises an assurance finding for a developer.",
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": f"Please summarise this finding: {finding}",
                    }
                }
            ]
        }

    return error_response(None, -32602, f"Prompt not found: {name}")


def call_tool(params):
    if not isinstance(params, dict):
        return invalid_params(None, "tools/call params must be an object")

    name = params.get("name")
    arguments = params.get("arguments", {})
    if not isinstance(name, str) or not name:
        return invalid_params(None, "tools/call name must be a non-empty string")

    if not isinstance(arguments, dict):
        return invalid_params(None, "tools/call arguments must be an object")

    if name == "calculator":
        try:
            operation = arguments["operation"]
            a = float(arguments["a"])
            b = float(arguments["b"])
        except (KeyError, TypeError, ValueError):
            return invalid_params(None, "calculator arguments are invalid")

        if operation == "add":
            value = a + b
        elif operation == "subtract":
            value = a - b
        elif operation == "multiply":
            value = a * b
        elif operation == "divide":
            if b == 0:
                return error_response(None, -32602, "Division by zero")
            value = a / b
        else:
            return error_response(None, -32602, "Unsupported operation")

        return {
            "content": [
                {
                    "type": "text",
                    "text": str(value),
                }
            ],
            "isError": False,
        }

    if name == "echo":
        text = arguments.get("text")
        if not isinstance(text, str):
            return invalid_request(None, "echo.text must be a string")
        return {
            "content": [
                {
                    "type": "text",
                    "text": text,
                }
            ],
            "isError": False,
        }

    return error_response(None, -32602, f"Unknown tool: {name}")


def handle_message(data):
    if not isinstance(data, dict):
        return invalid_request(None, "JSON-RPC message must be an object")

    # A JSON-RPC message with no "id", or an explicit null "id", is a
    # notification. The server MUST NOT send any response to a notification.
    is_notification = "id" not in data or data.get("id") is None

    request_id = data.get("id")

    if data.get("jsonrpc") != "2.0":
        if is_notification:
            return None
        return invalid_request(request_id, "jsonrpc must be 2.0")

    method = data.get("method")
    if not isinstance(method, str) or not method:
        if is_notification:
            return None
        return invalid_request(request_id, "method must be a non-empty string")

    if is_notification:
        return None

    if isinstance(data["id"], bool) or not isinstance(data["id"], (str, int)):
        return invalid_request(request_id, "id must be a string or integer")

    params = data.get("params", {})
    if params is not None and not isinstance(params, dict):
        return invalid_request(request_id, "params must be an object")

    if method == "initialize":
        if not isinstance(params, dict):
            return invalid_params(request_id, "initialize params must be an object")

        if params.get("protocolVersion") != PROTOCOL_VERSION:
            return invalid_params(request_id, "Unsupported protocol version")

        if not isinstance(params.get("capabilities"), dict):
            return invalid_params(request_id, "capabilities must be an object")

        client_info = params.get("clientInfo")
        if not isinstance(client_info, dict):
            return invalid_params(request_id, "clientInfo must be an object")

        if not isinstance(client_info.get("name"), str) or not client_info["name"]:
            return invalid_params(request_id, "clientInfo.name is required")

        if not isinstance(client_info.get("version"), str):
            return invalid_params(request_id, "clientInfo.version is required")

        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
                "prompts": {"listChanged": False},
            },
            "serverInfo": {
                "name": "local-assurance-demo-server",
                "title": "Local Assurance Demo Server",
                "version": "1.0.0",
            },
        }
        return success_response(request_id, result)

    if method == "ping":
        return success_response(request_id, {})

    if method == "tools/list":
        return success_response(request_id, list_tools())

    if method == "resources/list":
        return success_response(request_id, list_resources())

    if method == "resources/read":
        result = read_resource(params)
        if "error" in result:
            result["id"] = request_id
            return result
        return success_response(request_id, result)

    if method == "prompts/list":
        return success_response(request_id, list_prompts())

    if method == "prompts/get":
        result = get_prompt(params)
        if "error" in result:
            result["id"] = request_id
            return result
        return success_response(request_id, result)

    if method == "tools/call":
        result = call_tool(params)
        if "error" in result:
            result["id"] = request_id
            return result
        return success_response(request_id, result)

    return method_not_found(request_id, method)


@app.after_request
def add_protocol_version_header(response):
    """Echo the negotiated MCP-Protocol-Version on every HTTP response, as the
    HTTP transport requires (MCP spec 2025-11-25 §2.4)."""
    response.headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
    return response


@app.route("/.well-known/oauth-authorization-server", methods=["GET"])
def oauth_authorization_server_metadata():
    """Minimal OAuth 2.1 authorization-server metadata document (MCP spec
    2025-11-25 §6.3). Advertised for conformance probing; the test server is
    open/public and does not actually enforce these flows."""
    return jsonify(
        {
            "issuer": "http://127.0.0.1:8000",
            "authorization_endpoint": "http://127.0.0.1:8000/oauth/authorize",
            "token_endpoint": "http://127.0.0.1:8000/oauth/token",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
        }
    )


@app.route("/", methods=["POST"])
def mcp_endpoint():
    raw_body = request.get_data(as_text=True)
    try:
        data = json.loads(raw_body)
    except JSONDecodeError:
        return jsonify(parse_error()), 400

    if isinstance(data, list):
        responses = [
            response for response in (handle_message(message) for message in data)
            if response is not None
        ]
        if not responses:
            return "", 204
        return jsonify(responses)

    response = handle_message(data)
    if response is None:
        return "", 202
    return jsonify(response)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=False)
