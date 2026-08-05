#!/usr/bin/env python
"""
Differential / interoperability testing for MCP servers.

Sends the *identical* 15-request MCP sequence to two or more servers and flags
observable divergences in their responses (response type, error code, presence
of the jsonrpc field). This surfaces interoperability gaps automatically: where
one server returns a proper error, another may silently drop the request or
reply with a different code.

Outputs:
  reports/differential/differential_report.json
  reports/differential/differential_report.html
  a console summary

Run:  python differential.py
"""
import json
import sys
from pathlib import Path

import survey  # for _ensure_launcher (npx/uvx resolution)
from core.client import HttpMCPClient, StdioMCPClient

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

OUT_DIR = Path("reports/differential")
PROTOCOL_VERSION = "2025-11-25"
INIT_PARAMS = {
    "protocolVersion": PROTOCOL_VERSION,
    "capabilities": {},
    "clientInfo": {"name": "differential", "version": "1.0"},
}


def build_requests():
    """The standard 15-request sequence sent to every server."""
    return [
        {"name": "initialize", "method": "initialize", "mode": "payload",
         "sent_id": "d1",
         "payload": {"jsonrpc": "2.0", "id": "d1", "method": "initialize",
                     "params": INIT_PARAMS}},
        {"name": "notifications/initialized",
         "method": "notifications/initialized", "mode": "payload",
         "sent_id": None,
         "payload": {"jsonrpc": "2.0", "method": "notifications/initialized",
                     "params": {}}},
        {"name": "tools/list", "method": "tools/list", "mode": "payload",
         "sent_id": "d3",
         "payload": {"jsonrpc": "2.0", "id": "d3", "method": "tools/list",
                     "params": {}}},
        {"name": "resources/list", "method": "resources/list",
         "mode": "payload", "sent_id": "d4",
         "payload": {"jsonrpc": "2.0", "id": "d4", "method": "resources/list",
                     "params": {}}},
        {"name": "prompts/list", "method": "prompts/list", "mode": "payload",
         "sent_id": "d5",
         "payload": {"jsonrpc": "2.0", "id": "d5", "method": "prompts/list",
                     "params": {}}},
        {"name": "unknown method", "method": "nonexistent/method",
         "mode": "payload", "sent_id": "d6",
         "payload": {"jsonrpc": "2.0", "id": "d6",
                     "method": "nonexistent/method", "params": {}}},
        {"name": "null method", "method": "(null)", "mode": "payload",
         "sent_id": "d7",
         "payload": {"jsonrpc": "2.0", "id": "d7", "method": None,
                     "params": {}}},
        {"name": "empty string method", "method": "(empty)",
         "mode": "payload", "sent_id": "d8",
         "payload": {"jsonrpc": "2.0", "id": "d8", "method": "",
                     "params": {}}},
        {"name": "no id (notification)", "method": "ping", "mode": "payload",
         "sent_id": None,
         "payload": {"jsonrpc": "2.0", "method": "ping", "params": {}}},
        {"name": "invalid jsonrpc version", "method": "tools/list",
         "mode": "payload", "sent_id": "d10",
         "payload": {"jsonrpc": "1.0", "id": "d10", "method": "tools/list",
                     "params": {}}},
        {"name": "missing jsonrpc field", "method": "tools/list",
         "mode": "payload", "sent_id": "d11",
         "payload": {"id": "d11", "method": "tools/list", "params": {}}},
        {"name": "malformed JSON body", "method": "(raw)", "mode": "raw",
         "sent_id": None, "raw": '{"jsonrpc":"2.0","method":'},
        {"name": "non-object JSON body", "method": "(raw)", "mode": "raw",
         "sent_id": None, "raw": '"just a string"'},
        {"name": "array params", "method": "tools/list", "mode": "payload",
         "sent_id": "d14",
         "payload": {"jsonrpc": "2.0", "id": "d14", "method": "tools/list",
                     "params": []}},
        {"name": "missing method field", "method": "(none)",
         "mode": "payload", "sent_id": "d15",
         "payload": {"jsonrpc": "2.0", "id": "d15", "params": {}}},
    ]


def classify(resp, sent_id):
    """Reduce a ClientResponse to the four observable fields."""
    id_default = None if sent_id is None else False
    if resp.has_transport_error:
        te = (resp.transport_error or "").lower()
        rtype = "no_response" if "timed out" in te else "transport_error"
        return {"response_type": rtype, "error_code": None,
                "has_jsonrpc_field": False, "id_echoed": id_default}
    body = resp.body
    if body is None:
        # empty body (e.g. notification ack / HTTP 202/204)
        return {"response_type": "no_response", "error_code": None,
                "has_jsonrpc_field": False, "id_echoed": id_default}
    if not isinstance(body, dict):
        return {"response_type": "transport_error", "error_code": None,
                "has_jsonrpc_field": False, "id_echoed": id_default}
    has_jsonrpc = "jsonrpc" in body
    id_echoed = None if sent_id is None else (body.get("id") == sent_id)
    if "result" in body:
        return {"response_type": "result", "error_code": None,
                "has_jsonrpc_field": has_jsonrpc, "id_echoed": id_echoed}
    if "error" in body:
        err = body.get("error")
        code = err.get("code") if isinstance(err, dict) else None
        return {"response_type": "error",
                "error_code": code if isinstance(code, int) else None,
                "has_jsonrpc_field": has_jsonrpc, "id_echoed": id_echoed}
    # dict with neither result nor error
    return {"response_type": "no_response", "error_code": None,
            "has_jsonrpc_field": has_jsonrpc, "id_echoed": id_echoed}


class DifferentialTester:
    """Sends one identical request sequence to many servers and flags
    cross-server divergences in the observable responses."""

    def __init__(self, targets, protocol_version=PROTOCOL_VERSION,
                 per_request_timeout=6, startup_timeout=45):
        self.targets = targets
        self.pv = protocol_version
        self.timeout = per_request_timeout
        self.startup_timeout = startup_timeout
        self.requests = build_requests()
        self.observations = {}  # server name -> {request name -> observation}
        survey._ensure_launcher("npx")
        survey._ensure_launcher("uvx")

    def _make_client(self, target):
        if target.get("transport") == "http" or target.get("url"):
            return HttpMCPClient(target["url"], timeout=self.timeout,
                                 protocol_version=self.pv)
        return StdioMCPClient(target["command"], timeout=self.timeout,
                              startup_timeout=self.startup_timeout,
                              protocol_version=self.pv)

    def _send(self, client, req):
        if req["mode"] == "raw":
            return client.send_raw(req["raw"])
        return client.send_payload(req["payload"])

    def run(self):
        for target in self.targets:
            print(f"  probing {target['name']} ...", flush=True)
            obs = {}
            client = None
            dead = {"response_type": "transport_error", "error_code": None,
                    "has_jsonrpc_field": False, "id_echoed": None}
            try:
                client = self._make_client(target)
                for req in self.requests:
                    try:
                        resp = self._send(client, req)
                        obs[req["name"]] = classify(resp, req["sent_id"])
                    except Exception:  # noqa: BLE001
                        obs[req["name"]] = dict(dead)
            except Exception:  # noqa: BLE001 - server failed to start at all
                for req in self.requests:
                    obs.setdefault(req["name"], dict(dead))
            finally:
                if client is not None:
                    try:
                        client.close()
                    except Exception:  # noqa: BLE001
                        pass
            self.observations[target["name"]] = obs
        return self.detect_divergences()

    def detect_divergences(self):
        divergences = []
        for req in self.requests:
            rname = req["name"]
            per_server = [
                {"name": t["name"],
                 **{k: self.observations[t["name"]][rname][k]
                    for k in ("response_type", "error_code", "has_jsonrpc_field")}}
                for t in self.targets
            ]

            rtypes = {p["response_type"] for p in per_server}
            if len(rtypes) > 1:
                divergences.append(self._record(
                    req, per_server, "response_type_mismatch",
                    "Response type differs: " + ", ".join(
                        f"{p['name']}={p['response_type']}" for p in per_server)))

            err_codes = {p["error_code"] for p in per_server
                         if p["response_type"] == "error"}
            if len(err_codes) > 1:
                divergences.append(self._record(
                    req, per_server, "error_code_mismatch",
                    "Error codes differ: " + ", ".join(
                        f"{p['name']}={p['error_code']}" for p in per_server
                        if p["response_type"] == "error")))

            jflags = {p["has_jsonrpc_field"] for p in per_server}
            if len(jflags) > 1:
                divergences.append(self._record(
                    req, per_server, "jsonrpc_field_mismatch",
                    "jsonrpc field presence differs: " + ", ".join(
                        f"{p['name']}={p['has_jsonrpc_field']}"
                        for p in per_server)))
        return divergences

    @staticmethod
    def _record(req, per_server, dtype, description):
        return {
            "request_name": req["name"],
            "request_method": req["method"],
            "per_server_observations": per_server,
            "divergence_type": dtype,
            "description": description,
        }

    def per_server_summary(self):
        out = []
        for t in self.targets:
            obs = self.observations[t["name"]]
            out.append({
                "name": t["name"],
                "sdk": t.get("sdk", "?"),
                "source": t.get("source", "?"),
                "requests_sent": len(self.requests),
                "responses_received": sum(
                    1 for o in obs.values()
                    if o["response_type"] in ("result", "error")),
                "transport_errors": sum(
                    1 for o in obs.values()
                    if o["response_type"] == "transport_error"),
            })
        return out


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render_html(tester, divergences):
    targets = tester.targets
    summary = tester.per_server_summary()
    divergent_reqs = {d["request_name"] for d in divergences}

    # Per-server summary table
    srv_rows = ""
    for s in summary:
        srv_rows += (
            f"<tr><td>{_esc(s['name'])}</td><td>{s['sdk']}</td>"
            f"<td>{s['source']}</td><td class='num'>{s['requests_sent']}</td>"
            f"<td class='num'>{s['responses_received']}</td>"
            f"<td class='num'>{s['transport_errors']}</td></tr>")

    # Divergence matrix: rows = requests, cols = servers
    head_cells = "".join(f"<th>{_esc(t['name'])}</th>" for t in targets)
    matrix_rows = ""
    for req in tester.requests:
        rname = req["name"]
        diverged = rname in divergent_reqs
        cells = ""
        for t in targets:
            o = tester.observations[t["name"]][rname]
            code = f" ({o['error_code']})" if o["error_code"] is not None else ""
            jflag = "J" if o["has_jsonrpc_field"] else "-"
            cls = {
                "result": "ok", "error": "err", "no_response": "drop",
                "transport_error": "te",
            }.get(o["response_type"], "")
            cells += (f"<td class='{cls}'>{o['response_type']}{code}"
                      f"<span class='j'>{jflag}</span></td>")
        rowcls = "diverge" if diverged else ""
        matrix_rows += (f"<tr class='{rowcls}'><td class='reqname'>"
                        f"{_esc(rname)}{' &#9888;' if diverged else ''}</td>"
                        f"{cells}</tr>")

    # Divergence detail list
    div_items = ""
    for d in divergences:
        div_items += (
            f"<li><span class='tag'>{d['divergence_type']}</span> "
            f"<b>{_esc(d['request_name'])}</b> "
            f"<span class='mono'>({_esc(d['request_method'])})</span><br>"
            f"<span class='desc'>{_esc(d['description'])}</span></li>")
    if not div_items:
        div_items = "<li>No divergences detected.</li>"

    repl = {
        "__TARGETS__": str(len(targets)),
        "__REQS__": str(len(tester.requests)),
        "__DIVS__": str(len(divergences)),
        "__SRV_ROWS__": srv_rows,
        "__MATRIX_HEAD__": head_cells,
        "__MATRIX_ROWS__": matrix_rows,
        "__DIV_ITEMS__": div_items,
    }
    html = _HTML_TEMPLATE
    for k, v in repl.items():
        html = html.replace(k, v)
    return html


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MCP Differential / Interoperability Report</title>
<style>
  body { font-family:-apple-system,Segoe UI,Roboto,sans-serif; background:#0f172a; color:#e2e8f0; margin:0; padding:24px; }
  h1 { font-size:1.7rem; } h2 { color:#93c5fd; margin-top:28px; }
  .summary { display:flex; gap:24px; margin:14px 0 6px; }
  .stat { background:#1e293b; border:1px solid #334155; border-radius:10px; padding:14px 22px; }
  .stat .n { font-size:1.9rem; font-weight:700; } .stat .l { color:#94a3b8; font-size:0.8rem; text-transform:uppercase; }
  table { width:100%; border-collapse:collapse; font-size:0.86rem; margin-top:10px; }
  th { text-align:left; background:#334155; padding:8px; }
  td { padding:6px 8px; border-bottom:1px solid #273449; }
  td.num { text-align:right; font-variant-numeric:tabular-nums; }
  td.reqname { font-weight:600; white-space:nowrap; }
  tr.diverge { background:#3b1d2a; }
  tr.diverge td.reqname { color:#fda4af; }
  td.ok { color:#34d399; } td.err { color:#fbbf24; } td.drop { color:#94a3b8; } td.te { color:#f87171; }
  .j { color:#64748b; font-size:0.7rem; margin-left:4px; }
  ul { line-height:1.7; } li { margin-bottom:8px; }
  .tag { background:#7f1d1d; color:#fecaca; padding:1px 7px; border-radius:5px; font-size:0.75rem; }
  .mono { font-family:monospace; color:#94a3b8; } .desc { color:#cbd5e1; }
  .legend { color:#94a3b8; font-size:0.8rem; margin-top:6px; }
</style>
</head>
<body>
  <h1>MCP Differential / Interoperability Report</h1>
  <div class="summary">
    <div class="stat"><div class="n">__TARGETS__</div><div class="l">Servers compared</div></div>
    <div class="stat"><div class="n">__REQS__</div><div class="l">Requests each</div></div>
    <div class="stat"><div class="n">__DIVS__</div><div class="l">Divergences</div></div>
  </div>

  <h2>Per-Server Summary</h2>
  <table>
    <thead><tr><th>Server</th><th>SDK</th><th>Source</th><th>Requests Sent</th><th>Responses Received</th><th>Transport Errors</th></tr></thead>
    <tbody>__SRV_ROWS__</tbody>
  </table>

  <h2>Response Matrix (divergent rows highlighted)</h2>
  <p class="legend">Cell = response type [error code] (J = jsonrpc field present, - = absent). &#9888; marks a request where servers diverge.</p>
  <table>
    <thead><tr><th>Request</th>__MATRIX_HEAD__</tr></thead>
    <tbody>__MATRIX_ROWS__</tbody>
  </table>

  <h2>Divergences</h2>
  <ul>__DIV_ITEMS__</ul>
</body>
</html>"""


def write_reports(tester, divergences):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "targets_compared": [t["name"] for t in tester.targets],
        "request_count": len(tester.requests),
        "divergence_count": len(divergences),
        "divergences": divergences,
        "per_server_summary": tester.per_server_summary(),
    }
    (OUT_DIR / "differential_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    (OUT_DIR / "differential_report.html").write_text(
        render_html(tester, divergences), encoding="utf-8")
    return report


def print_summary(tester, divergences):
    print("\n" + "=" * 70)
    print("MCP DIFFERENTIAL / INTEROPERABILITY SUMMARY")
    print("=" * 70)
    print(f"Servers compared:  {len(tester.targets)} "
          f"({', '.join(t['name'] for t in tester.targets)})")
    print(f"Requests per server: {len(tester.requests)}")
    print(f"Divergences found:   {len(divergences)}")

    print("\n----- Per-server summary -----")
    for s in tester.per_server_summary():
        print(f"  {s['name']:<24} {s['sdk']:<11} sent={s['requests_sent']} "
              f"responded={s['responses_received']} "
              f"transport_errors={s['transport_errors']}")

    if divergences:
        print("\n----- Divergences -----")
        for d in divergences:
            print(f"  [{d['divergence_type']}] {d['request_name']}")
            print(f"     {d['description']}")
    print("=" * 70 + "\n")


def default_targets():
    """A compliant reference vs two real SDK servers - a rich differential."""
    return [
        {"name": "local-sample (compliant)", "transport": "stdio",
         "command": f'"{sys.executable}" -m sample_server.stdio_app',
         "sdk": "reference", "source": "local"},
        {"name": "server-everything", "transport": "stdio",
         "command": "npx -y @modelcontextprotocol/server-everything",
         "sdk": "typescript", "source": "official"},
        {"name": "mcp-server-time", "transport": "stdio",
         "command": "uvx mcp-server-time",
         "sdk": "python", "source": "official"},
    ]


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Differential / interoperability testing for MCP servers.",
    )
    parser.add_argument(
        "--compare-sdks",
        action="store_true",
        help="Compare the default reference vs TypeScript-SDK vs Python-SDK "
             "servers (this is also the default behaviour).",
    )
    parser.parse_args()

    targets = default_targets()
    print(f"Differential test: {len(targets)} servers x 15 requests\n")
    tester = DifferentialTester(targets)
    divergences = tester.run()
    report = write_reports(tester, divergences)
    print_summary(tester, divergences)
    print(f"JSON report: {OUT_DIR / 'differential_report.json'}")
    print(f"HTML report: {OUT_DIR / 'differential_report.html'}")
    return report


if __name__ == "__main__":
    main()
