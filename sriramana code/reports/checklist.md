# MCP Server Conformance Checklist

## How to use this checklist

Run the assurance suite against your server (`python main.py --server-url <your-url>` for HTTP, or `python main.py --transport stdio --command "<your cmd>"` for STDIO) and work through the items below. **Fix every MUST item before submitting to a registry** — MUST failures are hard conformance violations. SHOULD items are strong recommendations; address them where practical. Tick each box once your server passes that case.

_Total: 34 assurance cases across 6 categories._


## Protocol Conformance (8 cases)

### MUST requirements

- [ ] **Initialize Handshake** — MCP spec 2025-11-25 §3.1 — initialize lifecycle
  Requirement: Respond to initialize with a result carrying protocolVersion, capabilities, and serverInfo.
  Test: Sends initialize (protocolVersion 2025-11-25 + clientInfo); expects a valid initialize result.
  Correct response: `{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-11-25","capabilities":{},"serverInfo":{"name":"my-server","version":"1.0.0"}}}`

- [ ] **Initialized Notification** — MCP spec 2025-11-25 §3.1 — notifications/initialized
  Requirement: Accept the notifications/initialized notification after initialize and send no response to it.
  Test: Performs initialize then sends notifications/initialized; expects acceptance (HTTP 200/202/204) with no body.
  Correct response: (no response body — notifications/initialized is a notification; reply 202/204 empty)

- [ ] **Unknown Method Rejection** — JSON-RPC 2.0 §5.1 — method not found (-32601)
  Requirement: Return METHOD_NOT_FOUND (-32601) for any method name the server does not implement.
  Test: Sends a request for a method the server does not implement; expects a -32601 error.
  Correct response: `{"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"Method not found"}}`

- [ ] **Missing Id Treated as Notification** — JSON-RPC 2.0 §4 — no-id message is notification
  Requirement: Treat a request with no id as a notification and send no response.
  Test: Sends a method call with no id field; expects silence (no response body).
  Correct response: (no response — a JSON-RPC message without an id is a notification)

- [ ] **Null Id Treated as Notification** — JSON-RPC 2.0 §4 — null-id message is notification
  Requirement: Treat a request with an explicit null id as a notification and send no response.
  Test: Sends initialize with id:null; expects silence (no response body).
  Correct response: (no response — a null-id message is a notification)

### SHOULD recommendations

- [ ] **Pagination Cursor Handling** — MCP spec 2025-11-25 §5 — pagination cursor
  Requirement: Handle an unknown pagination cursor gracefully — ignore it and return a result, or reject it with a valid error.
  Test: Sends tools/list with an invalid cursor; expects a valid result or a valid JSON-RPC error (no crash).
  Correct response: `{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}`

- [ ] **Tools List Next Cursor** — MCP spec 2025-11-25 §5 — nextCursor in list responses
  Requirement: If a tools/list response includes a nextCursor field, it must be a string.
  Test: Inspects tools/list; any nextCursor present must be typed as a string.
  Correct response: `{"jsonrpc":"2.0","id":1,"result":{"tools":[],"nextCursor":"eyJwYWdlIjoyfQ=="}}`

- [ ] **Server Info Completeness** — MCP spec 2025-11-25 §3.1 — serverInfo fields
  Requirement: The initialize result's serverInfo should include a non-empty name and version.
  Test: Inspects serverInfo in the initialize result for both name and version.
  Correct response: `{"serverInfo":{"name":"my-server","version":"1.0.0"}}`


## Functional Correctness (7 cases)

### MUST requirements

- [ ] **Tools List Schema** — MCP spec 2025-11-25 §5.1 — tools/list response shape
  Requirement: If the tools capability is declared, tools/list must return well-formed tool definitions (name + inputSchema).
  Test: Calls tools/list; validates each tool has a name and an inputSchema object.
  Correct response: `{"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"calculator","inputSchema":{"type":"object"}}]}}`

- [ ] **Resources List Schema** — MCP spec 2025-11-25 §5.2 — resources/list response shape
  Requirement: If the resources capability is declared, resources/list must return entries with a uri and name.
  Test: Calls resources/list; validates each resource has a uri and name.
  Correct response: `{"jsonrpc":"2.0","id":1,"result":{"resources":[{"uri":"file:///x.txt","name":"x"}]}}`

- [ ] **Prompts List Schema** — MCP spec 2025-11-25 §5.3 — prompts/list response shape
  Requirement: If the prompts capability is declared, prompts/list must return entries with a name.
  Test: Calls prompts/list; validates each prompt has a name.
  Correct response: `{"jsonrpc":"2.0","id":1,"result":{"prompts":[{"name":"summarise"}]}}`

- [ ] **Resource Read Validation** — MCP spec 2025-11-25 §5.2 — resources/read response
  Requirement: resources/read must return a contents array of entries carrying a uri plus text or blob data.
  Test: Lists resources then reads the first; validates the contents array shape.
  Correct response: `{"jsonrpc":"2.0","id":1,"result":{"contents":[{"uri":"file:///x.txt","text":"..."}]}}`

- [ ] **Prompt Get Validation** — MCP spec 2025-11-25 §5.3 — prompts/get response
  Requirement: prompts/get must return a messages array of role/content message objects.
  Test: Lists prompts then gets the first; validates the messages array shape.
  Correct response: `{"jsonrpc":"2.0","id":1,"result":{"messages":[{"role":"user","content":{"type":"text","text":"..."}}]}}`

- [ ] **Advertised Tool Execution** — MCP spec 2025-11-25 §5.1 — tools/call response
  Requirement: An advertised tool must execute via tools/call and return a content array.
  Test: Calls an advertised tool (e.g. calculator add 2+3); expects a result with content and isError=false.
  Correct response: `{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"5"}],"isError":false}}`

- [ ] **Capability-Gated Tool Call** — MCP spec 2025-11-25 §3.2 — strict capability gating
  Requirement: Calling a non-existent tool must return an error (JSON-RPC error or result.isError=true), never a clean success.
  Test: Calls a tool name that does not exist; expects an error or isError=true.
  Correct response: `{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"Unknown tool"}],"isError":true}}`


## Basic Security Validation (5 cases)

### MUST requirements

- [ ] **Null Method Rejection** — JSON-RPC 2.0 §4 — method must be non-null string
  Requirement: Reject requests where method is null with INVALID_REQUEST (-32600).
  Test: Sends a request with method:null; expects INVALID_REQUEST (-32600).
  Correct response: `{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"Invalid Request"}}`

- [ ] **Invalid Method Type Rejection** — JSON-RPC 2.0 §4 — method must be string
  Requirement: Ensure method is a string type; reject numeric or boolean values.
  Test: Sends a request with a numeric method value; expects INVALID_REQUEST (-32600).
  Correct response: `{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"Invalid Request"}}`

- [ ] **Empty Method Rejection** — JSON-RPC 2.0 §4 — method must be non-empty
  Requirement: Validate that the method field is a non-empty string before dispatching.
  Test: Sends a request with method:"" (empty string); expects INVALID_REQUEST (-32600).
  Correct response: `{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"Invalid Request"}}`

- [ ] **Missing JSON-RPC Version Rejection** — JSON-RPC 2.0 §4 — jsonrpc field required
  Requirement: Validate jsonrpc field is present on every incoming request.
  Test: Sends a request omitting the jsonrpc field; expects INVALID_REQUEST (-32600).
  Correct response: `{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"Invalid Request"}}`

- [ ] **Invalid JSON-RPC Version Rejection** — JSON-RPC 2.0 §4 — jsonrpc must be exactly 2.0
  Requirement: Reject requests where jsonrpc is not exactly the string '2.0'.
  Test: Sends a request with jsonrpc:"1.0"; expects INVALID_REQUEST (-32600).
  Correct response: `{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"Invalid Request"}}`


## Advanced Negative Validation (7 cases)

### MUST requirements

- [ ] **Malformed JSON Parse Error** — JSON-RPC 2.0 §4.1 — parse error (-32700)
  Requirement: Return parse error (-32700) JSON body for all unparseable input.
  Test: Sends a truncated/unparseable JSON body; expects a -32700 parse error.
  Correct response: `{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"Parse error"}}`

- [ ] **Non-Object JSON Rejection** — JSON-RPC 2.0 §4 — request must be object
  Requirement: Return INVALID_REQUEST (-32600) when request body is valid JSON but not an object.
  Test: Sends a bare JSON string (valid JSON but not an object); expects -32600 with id null.
  Correct response: `{"jsonrpc":"2.0","id":null,"error":{"code":-32600,"message":"Invalid Request"}}`

- [ ] **Missing Method Field Rejection** — JSON-RPC 2.0 §4 — method field required
  Requirement: Return INVALID_REQUEST (-32600) when the method field is absent.
  Test: Sends a request object with no method field; expects -32600.
  Correct response: `{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"Invalid Request"}}`

- [ ] **Array Params Rejection** — JSON-RPC 2.0 §4 — params must be object not array
  Requirement: Reject requests where params is an array; MCP requires params to be an object.
  Test: Sends a request with params as an array; expects -32600.
  Correct response: `{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"Invalid Request"}}`

### SHOULD recommendations

- [ ] **Unsupported Protocol Version Handling** — MCP spec 2025-11-25 §3.1 — version negotiation
  Requirement: When the client requests an unsupported protocolVersion, reject with INVALID_PARAMS or negotiate a supported version.
  Test: Sends initialize with protocolVersion '1900-01-01'; expects an error or a negotiated supported version.
  Correct response: `{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"Unsupported protocol version"}}`

- [ ] **Missing Initialize Client Info Rejection** — MCP spec 2025-11-25 §3.1 — clientInfo field
  Requirement: Reject initialize requests that omit clientInfo with INVALID_PARAMS.
  Test: Sends initialize without clientInfo; expects -32602.
  Correct response: `{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"clientInfo is required"}}`

- [ ] **Invalid Tool Parameters Rejection** — MCP spec 2025-11-25 §5.1 — parameter validation
  Requirement: Reject tool calls whose arguments are the wrong type using INVALID_PARAMS.
  Test: Calls calculator with a non-numeric operand; expects -32602.
  Correct response: `{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"Invalid params"}}`


## Interoperability (2 cases)

### MUST requirements

- [ ] **String Request Id Echo** — JSON-RPC 2.0 §4 — id must be echoed in response
  Requirement: Echo the request id verbatim in the response, including string-typed ids.
  Test: Sends initialize with a string id; expects the same id echoed in the result.
  Correct response: `{"jsonrpc":"2.0","id":"assurance-string-id","result":{"protocolVersion":"2025-11-25"}}`

- [ ] **Declared Capability Consistency** — MCP spec 2025-11-25 §3.2 — capability negotiation
  Requirement: Every capability declared at initialize must be backed by a working list method.
  Test: For each declared capability (tools/resources/prompts) calls its list method and validates it.
  Correct response: (each declared capability's list method returns a valid result)


## Authorization Conformance (5 cases)

### MUST requirements

- [ ] **Protocol Version Header Enforcement** — MCP spec 2025-11-25 §2.4 — MCP-Protocol-Version header required
  Requirement: Handle an initialize sent without the MCP-Protocol-Version header without crashing (reject or accept — both conformant).
  Test: Sends initialize over HTTP with no MCP-Protocol-Version header; expects a valid result or a 4xx/JSON-RPC error.
  Correct response: (HTTP 200 with a valid initialize result, OR a 4xx / JSON-RPC error — either is conformant)

- [ ] **Transport Version Header in Response** — MCP spec 2025-11-25 §2.4 — MCP-Protocol-Version in responses
  Requirement: Echo the MCP-Protocol-Version header back on HTTP responses.
  Test: Sends a normal initialize over HTTP; checks the response carries an MCP-Protocol-Version header.
  Correct response: (HTTP response header) MCP-Protocol-Version: 2025-11-25

### SHOULD recommendations

- [ ] **Invalid Protocol Version Header Handling** — MCP spec 2025-11-25 §2.4 — version header validation
  Requirement: Reject or negotiate when the MCP-Protocol-Version header is clearly invalid.
  Test: Sends initialize with MCP-Protocol-Version: 0.0.0; expects rejection or negotiation to a supported version.
  Correct response: (error response, OR a result whose protocolVersion is a supported version — not '0.0.0')

- [ ] **OAuth Discovery Endpoint** — MCP spec 2025-11-25 §6.3 — OAuth 2.1 authorization server metadata
  Requirement: If authorization is used, expose OAuth 2.1 metadata at /.well-known/oauth-authorization-server (404 is fine for open servers).
  Test: GET /.well-known/oauth-authorization-server; expects JSON with issuer + authorization_endpoint, or 404 (advisory).
  Correct response: `{"issuer":"https://srv","authorization_endpoint":"https://srv/authorize","token_endpoint":"https://srv/token"}`

- [ ] **Unauthenticated Request Response** — MCP spec 2025-11-25 §6.3 — 401 with WWW-Authenticate on protected resources
  Requirement: An unauthenticated request must return 401 with WWW-Authenticate (protected) or 200 with a valid result (open).
  Test: Sends initialize with no Authorization header; expects 401+WWW-Authenticate or a 200 JSON-RPC result.
  Correct response: (HTTP 401 with a WWW-Authenticate header, OR HTTP 200 with a valid JSON-RPC result)

## Quick reference — most common violations

Top 5 cases most often not passed across 32 surveyed servers (FAIL or advisory WARN):

1. **Array Params Rejection** — 100.0% of servers did not pass (0 failed, 32 advisory) · Advanced Negative Validation · MUST
2. **Empty Method Rejection** — 100.0% of servers did not pass (31 failed, 1 advisory) · Basic Security Validation · MUST
3. **Invalid JSON-RPC Version Rejection** — 100.0% of servers did not pass (0 failed, 32 advisory) · Basic Security Validation · MUST
4. **Invalid Method Type Rejection** — 100.0% of servers did not pass (0 failed, 32 advisory) · Basic Security Validation · MUST
5. **Malformed JSON Parse Error** — 100.0% of servers did not pass (12 failed, 20 advisory) · Advanced Negative Validation · MUST

