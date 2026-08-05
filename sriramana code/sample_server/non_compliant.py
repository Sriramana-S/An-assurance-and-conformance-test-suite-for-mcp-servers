"""
Non-compliant MCP server that deliberately violates JSON-RPC and MCP protocol rules.
Used for testing the assurance framework's ability to detect protocol violations.
"""
import json
from flask import Flask, jsonify, request as flask_request

app = Flask(__name__)

PROTOCOL_VERSION = "2025-11-25"

# Violation flags - set these to enable specific violations
VIOLATIONS = {
    "missing_jsonrpc": False,
    "invalid_jsonrpc_version": False,
    "both_result_and_error": False,
    "neither_result_nor_error": False,
    "missing_id": False,
    "invalid_id_type": False,  # Will use null, boolean, or object
    "mismatched_id": False,
    "invalid_initialize_response": False,
    "missing_server_name": False,
    "missing_server_version": False,
    "invalid_protocol_version_type": False,
    "missing_capabilities": False,
    "invalid_tools_list": False,
    "invalid_resources_list": False,
    "invalid_prompts_list": False,
    "invalid_resources_read": False,
    "invalid_prompts_get": False,
    "skip_lifecycle_check": False,
    "reuse_request_ids": False,
    "invalid_error_code": False,
    "invalid_error_object": False,
    "invalid_error_code_type": False,
    "empty_error_message": False,
    "non_object_result": False,
    # Authorization-conformance toggles (HTTP transport, MCP spec §2.4 / §6.3).
    "missing_version_header": False,
    "missing_oauth_discovery": False,
}

# Track session state
session_state = {
    "initialized": False,
    "used_request_ids": set(),
}


def build_response_base(request_id, violation_type=None):
    """Build a response with optional violations."""
    response = {}

    if not VIOLATIONS["missing_jsonrpc"]:
        if VIOLATIONS["invalid_jsonrpc_version"]:
            response["jsonrpc"] = "1.0"
        else:
            response["jsonrpc"] = "2.0"

    if not VIOLATIONS["missing_id"]:
        if VIOLATIONS["invalid_id_type"]:
            # Use null, boolean, or object instead of string/int
            response["id"] = None
        elif VIOLATIONS["mismatched_id"]:
            response["id"] = request_id + 999
        else:
            response["id"] = request_id

    return response


def success_response(request_id, result):
    """Build a successful JSON-RPC response."""
    response = build_response_base(request_id)

    if not VIOLATIONS["both_result_and_error"] and not VIOLATIONS["neither_result_nor_error"]:
        response["result"] = result
    elif VIOLATIONS["both_result_and_error"]:
        response["result"] = result
        response["error"] = {"code": -1, "message": "This violates protocol"}
    elif VIOLATIONS["neither_result_nor_error"]:
        pass  # Response has neither result nor error

    return response


def error_response(request_id, code, message):
    """Build an error JSON-RPC response."""
    response = build_response_base(request_id)

    if VIOLATIONS["invalid_error_object"]:
        response["error"] = "This is not an object"
    elif VIOLATIONS["invalid_error_code_type"]:
        response["error"] = {
            "code": "not-an-integer",
            "message": message,
        }
    elif VIOLATIONS["empty_error_message"]:
        response["error"] = {
            "code": code,
            "message": "",
        }
    else:
        if VIOLATIONS["invalid_error_code"]:
            # Use error code outside standard range
            code = -99999
        response["error"] = {
            "code": code,
            "message": message,
        }

    return response


def parse_error():
    """Parse error response."""
    response = {}
    if not VIOLATIONS["missing_jsonrpc"]:
        response["jsonrpc"] = "2.0"
    if not VIOLATIONS["missing_id"]:
        response["id"] = None
    response["error"] = {"code": -32700, "message": "Parse error"}
    return response


def method_not_found(request_id, method):
    """Method not found response."""
    return error_response(request_id, -32601, f"Method not found: {method}")


def invalid_request(request_id, message="Invalid Request"):
    """Invalid request response."""
    return error_response(request_id, -32600, message)


def invalid_params(request_id, message="Invalid params"):
    """Invalid params response."""
    return error_response(request_id, -32602, message)


def list_tools():
    """Return tools list - can be invalid based on violations."""
    if VIOLATIONS["invalid_tools_list"]:
        return {
            "tools": [
                {
                    "name": "broken_tool",
                    # Intentionally missing inputSchema
                },
                {
                    "name": "",  # Invalid: empty name
                    "inputSchema": {},
                },
                "not_an_object",  # Invalid: tool is not an object
            ]
        }

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
        ]
    }


def list_resources():
    """Return resources list - can be invalid based on violations."""
    if VIOLATIONS["invalid_resources_list"]:
        return {
            "resources": [
                {
                    "uri": "",  # Invalid: empty uri
                    "name": "bad_resource",
                },
                {
                    "uri": "file:///test",
                    # Missing name
                },
                "not_an_object",  # Invalid: resource is not an object
            ]
        }

    return {
        "resources": [
            {
                "uri": "file:///demo/resource.txt",
                "name": "demo-resource",
                "title": "Demo Resource",
                "description": "Sample resource for testing.",
                "mimeType": "text/plain",
            },
        ]
    }


def list_prompts():
    """Return prompts list - can be invalid based on violations."""
    if VIOLATIONS["invalid_prompts_list"]:
        return {
            "prompts": [
                {
                    "name": "",  # Invalid: empty name
                    "arguments": [],
                },
                {
                    "name": "bad_prompt",
                    "arguments": "not_an_array",  # Invalid: should be array
                },
                "not_an_object",  # Invalid: prompt is not an object
            ]
        }

    return {
        "prompts": [
            {
                "name": "demo-prompt",
                "description": "A sample prompt.",
                "arguments": [],
            },
        ]
    }


def read_resource(params):
    """Return resource contents - can be invalid based on violations."""
    if VIOLATIONS["invalid_resources_read"]:
        return {
            "contents": [
                {
                    "uri": "",  # Invalid: empty
                },
                "not_an_object"
            ]
        }

    return {
        "contents": [
            {
                "uri": "file:///demo/resource.txt",
                "text": "Compliant text content",
            }
        ]
    }


def get_prompt(params):
    """Return prompt details - can be invalid based on violations."""
    if VIOLATIONS["invalid_prompts_get"]:
        return {
            "messages": [
                {
                    "role": "",  # Invalid
                    "content": "not_an_object"
                }
            ]
        }

    return {
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": "Hello compliance check",
                }
            }
        ]
    }


def get_initialize_response():
    """Build initialize response - can be invalid based on violations."""
    response = {
        "serverInfo": {
            "name": "non-compliant-mcp-server",
            "version": "1.0.0",
        },
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {
            "tools": {"listChanged": False},
            "resources": {"subscribe": False, "listChanged": False},
            "prompts": {"listChanged": False},
        },
    }

    if VIOLATIONS["invalid_initialize_response"]:
        # Remove all required fields
        response = {}

    if VIOLATIONS["missing_server_name"]:
        if "serverInfo" in response:
            response["serverInfo"]["name"] = ""

    if VIOLATIONS["missing_server_version"]:
        if "serverInfo" in response:
            del response["serverInfo"]["version"]

    if VIOLATIONS["invalid_protocol_version_type"]:
        response["protocolVersion"] = 2025  # Should be string

    if VIOLATIONS["missing_capabilities"]:
        if "capabilities" in response:
            del response["capabilities"]

    return response


@app.after_request
def add_protocol_version_header(response):
    """Echo MCP-Protocol-Version on every response (MCP spec §2.4) in clean
    mode. The missing_version_header violation suppresses it so the auth
    "Transport Version Header in Response" case degrades."""
    if not VIOLATIONS.get("missing_version_header"):
        response.headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
    return response


@app.route("/.well-known/oauth-authorization-server", methods=["GET"])
def oauth_authorization_server_metadata():
    """OAuth 2.1 authorization-server metadata (MCP spec §6.3). The
    missing_oauth_discovery violation returns 404 so the auth
    "OAuth Discovery Endpoint" case degrades to a WARN."""
    if VIOLATIONS.get("missing_oauth_discovery"):
        return jsonify({"error": "not found"}), 404
    return jsonify(
        {
            "issuer": "http://127.0.0.1:8001",
            "authorization_endpoint": "http://127.0.0.1:8001/oauth/authorize",
            "token_endpoint": "http://127.0.0.1:8001/oauth/token",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
        }
    )


@app.route("/", methods=["POST"])
def handle_request():
    """Main JSON-RPC request handler."""
    try:
        payload = flask_request.get_json(force=True)
    except Exception:
        # Gap 3: truly malformed JSON. Werkzeug's get_json(force=True) raises a
        # BadRequest (not a JSONDecodeError/ValueError), so catch broadly and
        # always return a JSON -32700 parse error body instead of an HTML 400.
        return jsonify(parse_error()), 400

    # Gap 4: valid JSON that is not a request object (e.g. a bare string or
    # array) is an INVALID_REQUEST (-32600), not a parse error (-32700).
    # parse_error is reserved for input that cannot be parsed at all.
    if not isinstance(payload, dict):
        return jsonify(
            error_response(None, -32600, "Request must be a JSON object")
        ), 400

    # A JSON-RPC message with no "id" (or an explicit null id) is a
    # notification. The server must stay silent: return 204 No Content with no
    # body, without dispatching to any method handler and without applying any
    # VIOLATIONS logic. Matches the notification-silence fix in app.py.
    if "id" not in payload or payload.get("id") is None:
        return "", 204

    request_id = payload.get("id")
    method = payload.get("method")

    # Validate basic structure
    if not isinstance(method, str) or not method:
        return jsonify(invalid_request(request_id, "method must be string")), 400

    # Gap 1: the jsonrpc field is required. Gated behind missing_jsonrpc so the
    # violation (omitting the check) is preserved exactly when the flag is True.
    if "jsonrpc" not in payload and not VIOLATIONS["missing_jsonrpc"]:
        return jsonify(
            error_response(request_id, -32600, "jsonrpc field is required")
        ), 400

    # Gap 2: the jsonrpc field must be exactly "2.0". Gated behind
    # invalid_jsonrpc_version so the violation is preserved when the flag is True.
    if (
        "jsonrpc" in payload
        and payload.get("jsonrpc") != "2.0"
        and not VIOLATIONS["invalid_jsonrpc_version"]
    ):
        return jsonify(
            error_response(request_id, -32600, "jsonrpc must be exactly 2.0")
        ), 400

    # Gap 5: params, when present, must be an object (not an array). There is no
    # violation toggle for this; it is validation that must always be active in
    # clean mode.
    if isinstance(payload.get("params"), list):
        return jsonify(
            error_response(request_id, -32600, "params must be an object")
        ), 400

    # An initialize request signals the start of a new session under the MCP
    # lifecycle. Reset per-session state before doing anything else so that
    # repeated runs against the same running process are reproducible and a
    # previous run's dirty state cannot leak into this one.
    if method == "initialize":
        session_state["initialized"] = False
        session_state["used_request_ids"] = set()

    # Lifecycle checks (unless skipped for testing)
    if not VIOLATIONS["skip_lifecycle_check"]:
        if method != "initialize" and not session_state["initialized"]:
            if method != "ping":
                return jsonify(error_response(request_id, -32600, "Must initialize first")), 400

    # Check for request id reuse
    if not VIOLATIONS["reuse_request_ids"]:
        if request_id in session_state["used_request_ids"]:
            return jsonify(error_response(request_id, -32600, "Duplicate request id")), 400
        if request_id is not None:
            session_state["used_request_ids"].add(request_id)

    # Handle methods
    if method == "initialize":
        # Always-on MCP validation: initialize params must include a clientInfo
        # object. A missing or non-object clientInfo is an INVALID_PARAMS error.
        init_params = payload.get("params", {})
        if not isinstance(init_params, dict) or not isinstance(
            init_params.get("clientInfo"), dict
        ):
            return jsonify(
                error_response(request_id, -32602, "clientInfo is required")
            ), 400

        session_state["initialized"] = True
        result = get_initialize_response()
        if VIOLATIONS["non_object_result"]:
            # Return result as array instead of object
            response = build_response_base(request_id)
            if not VIOLATIONS["missing_jsonrpc"]:
                response["jsonrpc"] = "2.0"
            response["result"] = ["not", "an", "object"]
            return jsonify(response), 200

        return jsonify(success_response(request_id, result)), 200

    elif method == "notifications/initialized":
        # This should be a notification (no id), but we handle it
        session_state["initialized"] = True
        return jsonify({"jsonrpc": "2.0"}), 200

    elif method == "tools/list":
        result = list_tools()
        return jsonify(success_response(request_id, result)), 200

    elif method == "resources/list":
        result = list_resources()
        return jsonify(success_response(request_id, result)), 200

    elif method == "resources/read":
        result = read_resource(payload.get("params", {}))
        return jsonify(success_response(request_id, result)), 200

    elif method == "prompts/list":
        result = list_prompts()
        return jsonify(success_response(request_id, result)), 200

    elif method == "prompts/get":
        result = get_prompt(payload.get("params", {}))
        return jsonify(success_response(request_id, result)), 200

    elif method == "tools/call":
        # Simple echo implementation
        params = payload.get("params", {})
        tool_name = params.get("name", "unknown")

        # Always-on MCP validation: the calculator tool requires numeric a and
        # b arguments. Missing or non-numeric values are an INVALID_PARAMS error.
        if tool_name == "calculator":
            arguments = params.get("arguments", {})
            if not isinstance(arguments, dict):
                arguments = {}
            a = arguments.get("a")
            b = arguments.get("b")
            if (
                not isinstance(a, (int, float)) or isinstance(a, bool)
                or not isinstance(b, (int, float)) or isinstance(b, bool)
            ):
                return jsonify(
                    error_response(
                        request_id, -32602, "calculator requires numeric a and b"
                    )
                ), 400
        else:
            # Always-on capability gating: only the advertised 'calculator' tool
            # exists, so any other name (e.g. a probe for a non-existent tool)
            # must return an error rather than a clean success.
            return jsonify(
                error_response(request_id, -32602, f"Unknown tool: {tool_name}")
            ), 400

        result = {
            "content": [
                {
                    "type": "text",
                    "text": f"Tool {tool_name} called successfully",
                }
            ],
            "isError": False,
        }
        return jsonify(success_response(request_id, result)), 200

    elif method == "ping":
        return jsonify(success_response(request_id, {})), 200

    else:
        return jsonify(method_not_found(request_id, method)), 400


def reset_violations():
    """Reset all violations to disabled state."""
    for key in VIOLATIONS:
        VIOLATIONS[key] = False
    session_state["initialized"] = False
    session_state["used_request_ids"] = set()


def set_violation(violation_name, enabled=True):
    """Enable or disable a specific violation."""
    if violation_name in VIOLATIONS:
        VIOLATIONS[violation_name] = enabled


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8001, debug=False)
