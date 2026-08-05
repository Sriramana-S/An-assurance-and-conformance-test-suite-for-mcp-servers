#!/usr/bin/env python
"""
Developer self-assessment checklist generator for the MCP Assurance Suite.

Turns the 34 assurance cases (core.suite.DEFAULT_CASES) into a practical
pre-submission checklist an MCP server developer can work through before
publishing to a registry. Outputs:

  reports/checklist.md    — Markdown checklist, grouped by category / level
  reports/checklist.html  — standalone, printable page with clickable
                            checkboxes and a live X/34 progress counter

Per-case requirement text and "correct response" JSON examples for the
negative-validation cases are sourced from core.unified_reporter.REMEDIATION_HINTS;
the remaining cases are described here.
"""
import json
import sys
from pathlib import Path

from core.suite import DEFAULT_CASES
from core.unified_reporter import REMEDIATION_HINTS, GENERIC_REMEDIATION

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
SURVEY_RESULTS = REPORTS / "survey" / "survey_results.json"
MD_OUT = REPORTS / "checklist.md"
HTML_OUT = REPORTS / "checklist.html"

CATEGORY_ORDER = [
    "Protocol Conformance",
    "Functional Correctness",
    "Basic Security Validation",
    "Advanced Negative Validation",
    "Interoperability",
    "Authorization Conformance",
]

# Authored requirement / test / correct-response guidance per case. For the 10
# cases present in REMEDIATION_HINTS, the requirement + correct example come
# from there; this guide always supplies the "Test" sentence and supplies
# requirement/correct for the remaining cases.
CASE_GUIDE = {
    # ---- Protocol Conformance ------------------------------------------- #
    "Initialize Handshake": {
        "requirement": "Respond to initialize with a result carrying protocolVersion, capabilities, and serverInfo.",
        "test": "Sends initialize (protocolVersion 2025-11-25 + clientInfo); expects a valid initialize result.",
        "correct": '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-11-25","capabilities":{},"serverInfo":{"name":"my-server","version":"1.0.0"}}}',
    },
    "Initialized Notification": {
        "requirement": "Accept the notifications/initialized notification after initialize and send no response to it.",
        "test": "Performs initialize then sends notifications/initialized; expects acceptance (HTTP 200/202/204) with no body.",
        "correct": "(no response body — notifications/initialized is a notification; reply 202/204 empty)",
    },
    "Unknown Method Rejection": {
        "test": "Sends a request for a method the server does not implement; expects a -32601 error.",
    },
    "Missing Id Treated as Notification": {
        "requirement": "Treat a request with no id as a notification and send no response.",
        "test": "Sends a method call with no id field; expects silence (no response body).",
        "correct": "(no response — a JSON-RPC message without an id is a notification)",
    },
    "Null Id Treated as Notification": {
        "requirement": "Treat a request with an explicit null id as a notification and send no response.",
        "test": "Sends initialize with id:null; expects silence (no response body).",
        "correct": "(no response — a null-id message is a notification)",
    },
    "Pagination Cursor Handling": {
        "requirement": "Handle an unknown pagination cursor gracefully — ignore it and return a result, or reject it with a valid error.",
        "test": "Sends tools/list with an invalid cursor; expects a valid result or a valid JSON-RPC error (no crash).",
        "correct": '{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}',
    },
    "Tools List Next Cursor": {
        "requirement": "If a tools/list response includes a nextCursor field, it must be a string.",
        "test": "Inspects tools/list; any nextCursor present must be typed as a string.",
        "correct": '{"jsonrpc":"2.0","id":1,"result":{"tools":[],"nextCursor":"eyJwYWdlIjoyfQ=="}}',
    },
    "Server Info Completeness": {
        "requirement": "The initialize result's serverInfo should include a non-empty name and version.",
        "test": "Inspects serverInfo in the initialize result for both name and version.",
        "correct": '{"serverInfo":{"name":"my-server","version":"1.0.0"}}',
    },
    # ---- Functional Correctness ----------------------------------------- #
    "Tools List Schema": {
        "requirement": "If the tools capability is declared, tools/list must return well-formed tool definitions (name + inputSchema).",
        "test": "Calls tools/list; validates each tool has a name and an inputSchema object.",
        "correct": '{"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"calculator","inputSchema":{"type":"object"}}]}}',
    },
    "Resources List Schema": {
        "requirement": "If the resources capability is declared, resources/list must return entries with a uri and name.",
        "test": "Calls resources/list; validates each resource has a uri and name.",
        "correct": '{"jsonrpc":"2.0","id":1,"result":{"resources":[{"uri":"file:///x.txt","name":"x"}]}}',
    },
    "Prompts List Schema": {
        "requirement": "If the prompts capability is declared, prompts/list must return entries with a name.",
        "test": "Calls prompts/list; validates each prompt has a name.",
        "correct": '{"jsonrpc":"2.0","id":1,"result":{"prompts":[{"name":"summarise"}]}}',
    },
    "Resource Read Validation": {
        "requirement": "resources/read must return a contents array of entries carrying a uri plus text or blob data.",
        "test": "Lists resources then reads the first; validates the contents array shape.",
        "correct": '{"jsonrpc":"2.0","id":1,"result":{"contents":[{"uri":"file:///x.txt","text":"..."}]}}',
    },
    "Prompt Get Validation": {
        "requirement": "prompts/get must return a messages array of role/content message objects.",
        "test": "Lists prompts then gets the first; validates the messages array shape.",
        "correct": '{"jsonrpc":"2.0","id":1,"result":{"messages":[{"role":"user","content":{"type":"text","text":"..."}}]}}',
    },
    "Advertised Tool Execution": {
        "requirement": "An advertised tool must execute via tools/call and return a content array.",
        "test": "Calls an advertised tool (e.g. calculator add 2+3); expects a result with content and isError=false.",
        "correct": '{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"5"}],"isError":false}}',
    },
    "Capability-Gated Tool Call": {
        "requirement": "Calling a non-existent tool must return an error (JSON-RPC error or result.isError=true), never a clean success.",
        "test": "Calls a tool name that does not exist; expects an error or isError=true.",
        "correct": '{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"Unknown tool"}],"isError":true}}',
    },
    # ---- Basic Security Validation (all in REMEDIATION_HINTS) ------------ #
    "Null Method Rejection": {
        "test": "Sends a request with method:null; expects INVALID_REQUEST (-32600).",
    },
    "Invalid Method Type Rejection": {
        "test": "Sends a request with a numeric method value; expects INVALID_REQUEST (-32600).",
    },
    "Empty Method Rejection": {
        "test": "Sends a request with method:\"\" (empty string); expects INVALID_REQUEST (-32600).",
    },
    "Missing JSON-RPC Version Rejection": {
        "test": "Sends a request omitting the jsonrpc field; expects INVALID_REQUEST (-32600).",
    },
    "Invalid JSON-RPC Version Rejection": {
        "test": "Sends a request with jsonrpc:\"1.0\"; expects INVALID_REQUEST (-32600).",
    },
    # ---- Advanced Negative Validation ----------------------------------- #
    "Malformed JSON Parse Error": {
        "test": "Sends a truncated/unparseable JSON body; expects a -32700 parse error.",
    },
    "Non-Object JSON Rejection": {
        "test": "Sends a bare JSON string (valid JSON but not an object); expects -32600 with id null.",
    },
    "Missing Method Field Rejection": {
        "test": "Sends a request object with no method field; expects -32600.",
    },
    "Array Params Rejection": {
        "test": "Sends a request with params as an array; expects -32600.",
    },
    "Unsupported Protocol Version Handling": {
        "requirement": "When the client requests an unsupported protocolVersion, reject with INVALID_PARAMS or negotiate a supported version.",
        "test": "Sends initialize with protocolVersion '1900-01-01'; expects an error or a negotiated supported version.",
        "correct": '{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"Unsupported protocol version"}}',
    },
    "Missing Initialize Client Info Rejection": {
        "requirement": "Reject initialize requests that omit clientInfo with INVALID_PARAMS.",
        "test": "Sends initialize without clientInfo; expects -32602.",
        "correct": '{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"clientInfo is required"}}',
    },
    "Invalid Tool Parameters Rejection": {
        "requirement": "Reject tool calls whose arguments are the wrong type using INVALID_PARAMS.",
        "test": "Calls calculator with a non-numeric operand; expects -32602.",
        "correct": '{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"Invalid params"}}',
    },
    # ---- Interoperability ----------------------------------------------- #
    "String Request Id Echo": {
        "requirement": "Echo the request id verbatim in the response, including string-typed ids.",
        "test": "Sends initialize with a string id; expects the same id echoed in the result.",
        "correct": '{"jsonrpc":"2.0","id":"assurance-string-id","result":{"protocolVersion":"2025-11-25"}}',
    },
    "Declared Capability Consistency": {
        "requirement": "Every capability declared at initialize must be backed by a working list method.",
        "test": "For each declared capability (tools/resources/prompts) calls its list method and validates it.",
        "correct": "(each declared capability's list method returns a valid result)",
    },
    # ---- Authorization Conformance -------------------------------------- #
    "Protocol Version Header Enforcement": {
        "requirement": "Handle an initialize sent without the MCP-Protocol-Version header without crashing (reject or accept — both conformant).",
        "test": "Sends initialize over HTTP with no MCP-Protocol-Version header; expects a valid result or a 4xx/JSON-RPC error.",
        "correct": "(HTTP 200 with a valid initialize result, OR a 4xx / JSON-RPC error — either is conformant)",
    },
    "Invalid Protocol Version Header Handling": {
        "requirement": "Reject or negotiate when the MCP-Protocol-Version header is clearly invalid.",
        "test": "Sends initialize with MCP-Protocol-Version: 0.0.0; expects rejection or negotiation to a supported version.",
        "correct": "(error response, OR a result whose protocolVersion is a supported version — not '0.0.0')",
    },
    "OAuth Discovery Endpoint": {
        "requirement": "If authorization is used, expose OAuth 2.1 metadata at /.well-known/oauth-authorization-server (404 is fine for open servers).",
        "test": "GET /.well-known/oauth-authorization-server; expects JSON with issuer + authorization_endpoint, or 404 (advisory).",
        "correct": '{"issuer":"https://srv","authorization_endpoint":"https://srv/authorize","token_endpoint":"https://srv/token"}',
    },
    "Unauthenticated Request Response": {
        "requirement": "An unauthenticated request must return 401 with WWW-Authenticate (protected) or 200 with a valid result (open).",
        "test": "Sends initialize with no Authorization header; expects 401+WWW-Authenticate or a 200 JSON-RPC result.",
        "correct": "(HTTP 401 with a WWW-Authenticate header, OR HTTP 200 with a valid JSON-RPC result)",
    },
    "Transport Version Header in Response": {
        "requirement": "Echo the MCP-Protocol-Version header back on HTTP responses.",
        "test": "Sends a normal initialize over HTTP; checks the response carries an MCP-Protocol-Version header.",
        "correct": "(HTTP response header) MCP-Protocol-Version: 2025-11-25",
    },
}


def case_detail(case):
    """Resolve (requirement, test, correct_response) for a case, preferring
    REMEDIATION_HINTS for the negative-validation cases."""
    guide = CASE_GUIDE.get(case.name, {})
    hint = REMEDIATION_HINTS.get(case.name)
    if hint:
        requirement = hint[0]
        correct = hint[1] or guide.get("correct", "")
    else:
        requirement = guide.get("requirement") or GENERIC_REMEDIATION
        correct = guide.get("correct", "")
    test = guide.get("test", "Run this suite case and compare the response to the spec clause.")
    return requirement, test, correct


def _is_json_example(s):
    return s.strip().startswith(("{", "["))


def grouped_cases():
    """Return {category: {'MUST': [...], 'SHOULD': [...]}} in canonical order,
    preserving DEFAULT_CASES declaration order within each bucket."""
    groups = {c: {"MUST": [], "SHOULD": []} for c in CATEGORY_ORDER}
    for case in DEFAULT_CASES:
        groups.setdefault(case.category, {"MUST": [], "SHOULD": []})
        groups[case.category].setdefault(case.conformance_level, []).append(case)
    return groups


# --------------------------------------------------------------------------- #
# Survey-derived "most common violations"
# --------------------------------------------------------------------------- #
def top_violations(limit=5):
    if not SURVEY_RESULTS.exists():
        return [], 0
    data = json.loads(SURVEY_RESULTS.read_text(encoding="utf-8"))
    tested = [r for r in data if r.get("status") == "tested"]
    n = len(tested)
    if not n:
        return [], 0
    cat = {c.name: c.category for c in DEFAULT_CASES}
    lvl = {c.name: c.conformance_level for c in DEFAULT_CASES}
    stats = {}
    for r in tested:
        for t in r.get("failed_tests", []):
            stats.setdefault(t, [0, 0])[0] += 1
        for t in r.get("warned_tests", []):
            stats.setdefault(t, [0, 0])[1] += 1
    rows = []
    for name, (failed, warned) in stats.items():
        nonpass = failed + warned
        rows.append({
            "name": name, "failed": failed, "warned": warned,
            "nonpass": nonpass, "rate": round(nonpass / n * 100, 1),
            "category": cat.get(name, "?"), "level": lvl.get(name, "?"),
        })
    rows.sort(key=lambda x: (-x["nonpass"], x["name"]))
    return rows[:limit], n


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #
def render_markdown(groups, violations, survey_n):
    out = []
    out.append("# MCP Server Conformance Checklist\n")
    out.append("## How to use this checklist\n")
    out.append(
        "Run the assurance suite against your server "
        "(`python main.py --server-url <your-url>` for HTTP, or "
        "`python main.py --transport stdio --command \"<your cmd>\"` for STDIO) "
        "and work through the items below. **Fix every MUST item before "
        "submitting to a registry** — MUST failures are hard conformance "
        "violations. SHOULD items are strong recommendations; address them "
        "where practical. Tick each box once your server passes that case.\n")

    total = sum(len(b["MUST"]) + len(b["SHOULD"])
                for b in groups.values())
    out.append(f"_Total: {total} assurance cases across "
               f"{len([c for c in CATEGORY_ORDER if groups.get(c)])} "
               f"categories._\n")

    for category in CATEGORY_ORDER:
        bucket = groups.get(category)
        if not bucket:
            continue
        count = len(bucket["MUST"]) + len(bucket["SHOULD"])
        out.append(f"\n## {category} ({count} cases)\n")
        for level, heading in (("MUST", "### MUST requirements"),
                               ("SHOULD", "### SHOULD recommendations")):
            cases = bucket.get(level, [])
            if not cases:
                continue
            out.append(f"{heading}\n")
            for case in cases:
                requirement, test, correct = case_detail(case)
                out.append(f"- [ ] **{case.name}** — {case.spec_clause}")
                out.append(f"  Requirement: {requirement}")
                out.append(f"  Test: {test}")
                if _is_json_example(correct):
                    out.append(f"  Correct response: `{correct}`")
                else:
                    out.append(f"  Correct response: {correct}")
                out.append("")  # blank line between items

    out.append("## Quick reference — most common violations\n")
    if violations:
        out.append(f"Top {len(violations)} cases most often not passed across "
                   f"{survey_n} surveyed servers (FAIL or advisory WARN):\n")
        for i, v in enumerate(violations, 1):
            out.append(
                f"{i}. **{v['name']}** — {v['rate']}% of servers did not pass "
                f"({v['failed']} failed, {v['warned']} advisory) "
                f"· {v['category']} · {v['level']}")
        out.append("")
    else:
        out.append("_No survey data available "
                   "(reports/survey/survey_results.json not found)._\n")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #
def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render_html(groups, violations, survey_n, total, must_n, should_n):
    sections = []
    for category in CATEGORY_ORDER:
        bucket = groups.get(category)
        if not bucket:
            continue
        count = len(bucket["MUST"]) + len(bucket["SHOULD"])
        sections.append(f"<h2>{_esc(category)} "
                        f"<span class='count'>({count} cases)</span></h2>")
        for level, heading, cls in (
                ("MUST", "MUST requirements", "must"),
                ("SHOULD", "SHOULD recommendations", "should")):
            cases = bucket.get(level, [])
            if not cases:
                continue
            sections.append(f"<h3 class='{cls}'>{heading}</h3>")
            for case in cases:
                requirement, test, correct = case_detail(case)
                if _is_json_example(correct):
                    correct_html = f"<code>{_esc(correct)}</code>"
                else:
                    correct_html = f"<span class='desc'>{_esc(correct)}</span>"
                sections.append(
                    "<label class='item'>"
                    "<input type='checkbox' class='case-check'>"
                    "<div class='body'>"
                    f"<div class='name'>{_esc(case.name)} "
                    f"<span class='clause'>{_esc(case.spec_clause)}</span></div>"
                    f"<div class='req'><b>Requirement:</b> {_esc(requirement)}</div>"
                    f"<div class='test'><b>Test:</b> {_esc(test)}</div>"
                    f"<div class='correct'><b>Correct response:</b> {correct_html}</div>"
                    "</div></label>")
    sections_html = "\n".join(sections)

    if violations:
        vitems = "".join(
            f"<li><b>{_esc(v['name'])}</b> — {v['rate']}% of servers did not "
            f"pass ({v['failed']} failed, {v['warned']} advisory) "
            f"<span class='clause'>{_esc(v['category'])} · {v['level']}</span></li>"
            for v in violations)
        quickref = (f"<p>Top {len(violations)} cases most often not passed "
                    f"across {survey_n} surveyed servers:</p><ol>{vitems}</ol>")
    else:
        quickref = "<p>No survey data available.</p>"

    return (_HTML_TEMPLATE
            .replace("__TOTAL__", str(total))
            .replace("__MUST__", str(must_n))
            .replace("__SHOULD__", str(should_n))
            .replace("__SECTIONS__", sections_html)
            .replace("__QUICKREF__", quickref))


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MCP Server Conformance Checklist</title>
<style>
  body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:0 24px 48px;}
  .scorebar{position:sticky;top:0;background:#111827;border-bottom:1px solid #334155;padding:14px 0;margin:0 -24px 8px;z-index:10;}
  .scorebar .inner{padding:0 24px;display:flex;align-items:center;gap:16px;flex-wrap:wrap;}
  .scorebar .score{font-size:1.25rem;font-weight:700;color:#34d399;}
  .bar{flex:1;min-width:160px;height:10px;background:#334155;border-radius:6px;overflow:hidden;}
  .bar > i{display:block;height:100%;width:0;background:#34d399;transition:width .15s;}
  h1{font-size:1.6rem;margin:16px 0 4px;} h2{color:#93c5fd;margin-top:30px;}
  h2 .count{color:#94a3b8;font-size:0.95rem;font-weight:400;}
  h3{margin:18px 0 6px;font-size:1rem;} h3.must{color:#f87171;} h3.should{color:#fbbf24;}
  .intro{color:#cbd5e1;max-width:880px;line-height:1.55;}
  .item{display:flex;gap:12px;background:#1e293b;border:1px solid #334155;border-radius:8px;padding:10px 14px;margin:8px 0;cursor:pointer;}
  .item input{margin-top:3px;width:18px;height:18px;flex:none;cursor:pointer;}
  .item .name{font-weight:600;} .item .clause{color:#94a3b8;font-weight:400;font-size:0.8rem;}
  .item .req,.item .test,.item .correct{font-size:0.85rem;color:#cbd5e1;margin-top:3px;}
  .item code{font-family:monospace;background:#0b1220;border:1px solid #334155;border-radius:4px;padding:1px 6px;color:#93c5fd;word-break:break-all;}
  .item .desc{color:#94a3b8;font-style:italic;}
  .item input:checked ~ .body .name{color:#34d399;text-decoration:line-through;}
  ol li{margin:6px 0;} .clause{color:#94a3b8;font-size:0.8rem;}
  @media print{
    body{background:#fff;color:#000;}
    .scorebar{position:static;background:#fff;border-bottom:1px solid #999;}
    .scorebar .score{color:#000;} .item{background:#fff;border:1px solid #999;break-inside:avoid;}
    h3.must{color:#b00;} h3.should{color:#a60;} .item code{background:#f3f3f3;color:#003;}
    .item .req,.item .test,.item .correct,.intro,.item .clause{color:#222;}
  }
</style></head><body>
<div class="scorebar"><div class="inner">
  <span class="score" id="score">0 / __TOTAL__</span>
  <span>items checked</span>
  <span class="bar"><i id="barfill"></i></span>
</div></div>
<h1>MCP Server Conformance Checklist</h1>
<p class="intro">Run the assurance suite against your server, then tick each box
once it passes. <b>Fix every MUST item before submitting to a registry</b> —
MUST failures are hard conformance violations. SHOULD items are strong
recommendations. This page has __MUST__ MUST and __SHOULD__ SHOULD cases
(__TOTAL__ total) and prints cleanly for offline review.</p>
__SECTIONS__
<h2>Quick reference &mdash; most common violations</h2>
__QUICKREF__
<script>
(function(){
  var boxes = document.querySelectorAll('input.case-check');
  var score = document.getElementById('score');
  var fill = document.getElementById('barfill');
  function update(){
    var n = 0;
    boxes.forEach(function(b){ if(b.checked) n++; });
    score.textContent = n + ' / ' + boxes.length;
    fill.style.width = (boxes.length ? (n / boxes.length * 100) : 0) + '%';
  }
  boxes.forEach(function(b){ b.addEventListener('change', update); });
  update();
})();
</script>
</body></html>"""


def main():
    groups = grouped_cases()
    total = sum(1 for _ in DEFAULT_CASES)
    must_n = sum(1 for c in DEFAULT_CASES if c.conformance_level == "MUST")
    should_n = sum(1 for c in DEFAULT_CASES if c.conformance_level == "SHOULD")
    n_categories = len([c for c in CATEGORY_ORDER if groups.get(c)])

    violations, survey_n = top_violations()

    REPORTS.mkdir(parents=True, exist_ok=True)
    MD_OUT.write_text(render_markdown(groups, violations, survey_n),
                      encoding="utf-8")
    HTML_OUT.write_text(
        render_html(groups, violations, survey_n, total, must_n, should_n),
        encoding="utf-8")

    print(f"Checklist generated: {total} items across {n_categories} "
          f"categories ({must_n} MUST, {should_n} SHOULD)")
    print(f"  Markdown: {MD_OUT}")
    print(f"  HTML:     {HTML_OUT}")


if __name__ == "__main__":
    main()
