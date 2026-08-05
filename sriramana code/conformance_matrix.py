#!/usr/bin/env python
"""
Formal conformance matrix for the MCP Assurance Suite.

Cross-tabulates all 34 assurance cases (core.suite.DEFAULT_CASES) against the
empirical real-world survey (reports/survey/survey_results.json) to produce a
citable research artifact:

  reports/survey/conformance_matrix.csv   — machine-readable matrix
  reports/survey/conformance_matrix.html  — standalone, colour-coded matrix

Methodology / limitations
-------------------------
The survey records, per server, only the *names* of failed and warned cases
(not passed/skipped names). A case that is neither failed nor warned on a given
server is therefore either PASS or SKIP. To attribute these correctly we run
the compliant local server over STDIO once and treat any case that SKIPs on
that baseline as transport-gated (HTTP-only) — those cases SKIP on every STDIO
survey target and are reported as N/A (all skipped). For all other cases the
"neither failed nor warned" servers are counted as passes; a handful of
per-server capability-gated SKIPs (e.g. resources/read on a server with no
resources) are not individually recorded by the survey and so fold into the
pass count. Rates are computed over *measured* servers (passed+failed+warned),
i.e. SKIP is excluded from the denominator — consistent with the suite's
MUST-compliance scoring.
"""
import csv
import json
import sys
from pathlib import Path

from core.suite import DEFAULT_CASES

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent
SURVEY_DIR = ROOT / "reports" / "survey"
SURVEY_RESULTS = SURVEY_DIR / "survey_results.json"
CSV_OUT = SURVEY_DIR / "conformance_matrix.csv"
HTML_OUT = SURVEY_DIR / "conformance_matrix.html"
PROTOCOL_VERSION = "2025-11-25"

LEVEL_ORDER = {"MUST": 0, "SHOULD": 1, "MAY": 2}


# --------------------------------------------------------------------------- #
# Data gathering
# --------------------------------------------------------------------------- #
def stdio_baseline_skips():
    """Run the compliant sample server over STDIO and return the set of case
    names that SKIP there (transport-gated / HTTP-only cases)."""
    from core.client import StdioMCPClient
    from core.suite import run_suite

    cmd = f'"{sys.executable}" -m sample_server.stdio_app'
    client = StdioMCPClient(
        cmd, timeout=5, protocol_version=PROTOCOL_VERSION, startup_timeout=30)
    try:
        results = run_suite(client, PROTOCOL_VERSION)
    finally:
        client.close()
    return {r.test for r in results if r.status == "SKIP"}


def load_tested_servers():
    if not SURVEY_RESULTS.exists():
        raise SystemExit(f"Survey results not found: {SURVEY_RESULTS}")
    data = json.loads(SURVEY_RESULTS.read_text(encoding="utf-8"))
    return [r for r in data if r.get("status") == "tested"]


def build_matrix(tested, transport_skipped):
    """Return one row dict per assurance case with per-case server tallies."""
    n = len(tested)
    rows = []
    for case in DEFAULT_CASES:
        name = case.name
        failed = sum(1 for s in tested if name in s.get("failed_tests", []))
        warned = sum(1 for s in tested if name in s.get("warned_tests", []))
        if name in transport_skipped:
            # HTTP-only case: skipped on every STDIO survey target.
            skipped = n
            passed = 0
        else:
            skipped = 0
            passed = n - failed - warned
        measured = passed + failed + warned
        if measured:
            pass_rate = round(passed / measured * 100, 1)
            fail_rate = round(failed / measured * 100, 1)
            adv_rate = round(warned / measured * 100, 1)
        else:
            pass_rate = fail_rate = adv_rate = None  # N/A (all skipped)
        rows.append({
            "name": name,
            "category": case.category,
            "level": case.conformance_level,
            "spec_clause": case.spec_clause,
            "tested": n,
            "passed": passed,
            "failed": failed,
            "warned": warned,
            "skipped": skipped,
            "pass_rate": pass_rate,
            "fail_rate": fail_rate,
            "adv_rate": adv_rate,
        })
    # Sort by Category, then Conformance Level (MUST before SHOULD), then Name.
    rows.sort(key=lambda r: (r["category"],
                             LEVEL_ORDER.get(r["level"], 9), r["name"]))
    # Assign sequential, citable Case IDs in the sorted order.
    for i, r in enumerate(rows, start=1):
        r["case_id"] = f"C{i:02d}"
    return rows


# --------------------------------------------------------------------------- #
# Output: CSV
# --------------------------------------------------------------------------- #
CSV_HEADER = [
    "Case ID", "Case Name", "Category", "Conformance Level", "Spec Clause",
    "Servers Tested", "Servers Passed", "Servers Failed", "Servers Warned",
    "Servers Skipped", "Pass Rate (%)", "Fail Rate (%)", "Advisory Rate (%)",
]


def _rate_cell(v):
    return "N/A" if v is None else f"{v:.1f}"


def write_csv(rows):
    SURVEY_DIR.mkdir(parents=True, exist_ok=True)
    with open(CSV_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        for r in rows:
            w.writerow([
                r["case_id"], r["name"], r["category"], r["level"],
                r["spec_clause"], r["tested"], r["passed"], r["failed"],
                r["warned"], r["skipped"], _rate_cell(r["pass_rate"]),
                _rate_cell(r["fail_rate"]), _rate_cell(r["adv_rate"]),
            ])


# --------------------------------------------------------------------------- #
# Output: HTML
# --------------------------------------------------------------------------- #
def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _cell_class(pass_rate):
    if pass_rate is None:
        return "na"
    if pass_rate >= 90:
        return "good"
    if pass_rate >= 60:
        return "warn"
    return "bad"


def write_html(rows, tested, transport_skipped):
    n = len(tested)
    must_n = sum(1 for r in rows if r["level"] == "MUST")
    should_n = sum(1 for r in rows if r["level"] == "SHOULD")
    measured = [r for r in rows if r["pass_rate"] is not None]
    mean_pass = (round(sum(r["pass_rate"] for r in measured) / len(measured), 1)
                 if measured else 0.0)

    body_rows = ""
    for r in rows:
        cls = _cell_class(r["pass_rate"])
        pr = "N/A" if r["pass_rate"] is None else f"{r['pass_rate']:.1f}%"
        fr = "N/A" if r["fail_rate"] is None else f"{r['fail_rate']:.1f}%"
        ar = "N/A" if r["adv_rate"] is None else f"{r['adv_rate']:.1f}%"
        body_rows += (
            f"<tr><td class='mono'>{r['case_id']}</td>"
            f"<td>{_esc(r['name'])}</td>"
            f"<td>{_esc(r['category'])}</td>"
            f"<td class='ctr'>{r['level']}</td>"
            f"<td class='clause'>{_esc(r['spec_clause'])}</td>"
            f"<td class='num'>{r['tested']}</td>"
            f"<td class='num'>{r['passed']}</td>"
            f"<td class='num'>{r['failed']}</td>"
            f"<td class='num'>{r['warned']}</td>"
            f"<td class='num'>{r['skipped']}</td>"
            f"<td class='num cell {cls}'>{pr}</td>"
            f"<td class='num'>{fr}</td>"
            f"<td class='num'>{ar}</td></tr>"
        )

    # Coverage summary: distinct spec clauses + measured cases per category.
    cov = {}
    for r in rows:
        c = cov.setdefault(r["category"], {"cases": 0, "clauses": set(),
                                           "measured": 0})
        c["cases"] += 1
        c["clauses"].add(r["spec_clause"])
        if r["pass_rate"] is not None:
            c["measured"] += 1
    cov_rows = ""
    for cat in sorted(cov):
        c = cov[cat]
        cov_rows += (
            f"<tr><td>{_esc(cat)}</td><td class='num'>{c['cases']}</td>"
            f"<td class='num'>{len(c['clauses'])}</td>"
            f"<td class='num'>{c['measured']}</td></tr>"
        )

    measured_total = len(measured)
    coverage_pct = round(measured_total / len(rows) * 100, 1) if rows else 0.0

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MCP Assurance Suite — Conformance Matrix</title>
<style>
  body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:24px;}}
  h1{{font-size:1.6rem;margin-bottom:2px;}} .sub{{color:#94a3b8;margin-bottom:18px;}}
  h2{{color:#93c5fd;margin-top:28px;}}
  .summary{{display:flex;flex-wrap:wrap;gap:16px;margin-bottom:8px;}}
  .stat{{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:12px 20px;}}
  .stat .n{{font-size:1.5rem;font-weight:700;}} .stat .l{{color:#94a3b8;font-size:0.72rem;text-transform:uppercase;}}
  table{{width:100%;border-collapse:collapse;font-size:0.85rem;margin-top:8px;}}
  th{{text-align:left;background:#334155;padding:7px;position:sticky;top:0;}}
  td{{padding:6px 8px;border-bottom:1px solid #273449;vertical-align:top;}}
  td.num{{text-align:right;font-variant-numeric:tabular-nums;}} td.ctr{{text-align:center;}}
  .mono{{font-family:monospace;color:#cbd5e1;}} .clause{{color:#94a3b8;font-size:0.78rem;}}
  td.cell{{font-weight:700;text-align:right;}}
  .good{{background:#14532d;color:#86efac;}} .warn{{background:#713f12;color:#fde68a;}}
  .bad{{background:#7f1d1d;color:#fecaca;}} .na{{background:#334155;color:#94a3b8;}}
  .legend{{margin-top:10px;font-size:0.8rem;color:#94a3b8;}}
  .legend span{{display:inline-block;padding:2px 8px;border-radius:4px;margin-right:8px;}}
  .note{{color:#94a3b8;font-size:0.8rem;margin-top:14px;max-width:1000px;line-height:1.5;}}
</style></head><body>
<h1>MCP Assurance Suite &mdash; Conformance Matrix</h1>
<div class="sub">{len(rows)} assurance cases across {n} servers</div>
<div class="summary">
  <div class="stat"><div class="n">{len(rows)}</div><div class="l">Total cases</div></div>
  <div class="stat"><div class="n">{must_n}</div><div class="l">MUST cases</div></div>
  <div class="stat"><div class="n">{should_n}</div><div class="l">SHOULD cases</div></div>
  <div class="stat"><div class="n">{mean_pass}%</div><div class="l">Mean pass rate (measured)</div></div>
  <div class="stat"><div class="n">{coverage_pct}%</div><div class="l">Empirical spec coverage</div></div>
</div>
<div class="legend">
  <span class="good">&ge; 90%</span><span class="warn">60&ndash;89%</span>
  <span class="bad">&lt; 60%</span><span class="na">N/A (all skipped)</span>
</div>
<table>
<thead><tr>
  <th>ID</th><th>Case Name</th><th>Category</th><th>Level</th><th>Spec Clause</th>
  <th>Tested</th><th>Pass</th><th>Fail</th><th>Warn</th><th>Skip</th>
  <th>Pass %</th><th>Fail %</th><th>Adv %</th>
</tr></thead>
<tbody>{body_rows}</tbody>
</table>
<h2>Spec Coverage by Category</h2>
<table>
<thead><tr><th>Category</th><th>Cases</th><th>Distinct Spec Clauses</th><th>Cases Measured</th></tr></thead>
<tbody>{cov_rows}</tbody>
</table>
<div class="note">
  Rates are computed over <b>measured</b> servers (Pass+Fail+Warn); SKIP is
  excluded from the denominator, consistent with the suite's MUST-compliance
  scoring. {len(transport_skipped)} HTTP-only case(s) SKIP on every STDIO survey
  target and are reported as N/A. Per-server capability-gated SKIPs are not
  individually recorded by the survey and fold into the pass count.
</div>
</body></html>"""


# --------------------------------------------------------------------------- #
# Console summary
# --------------------------------------------------------------------------- #
def print_summary(rows, transport_skipped):
    measured = [r for r in rows if r["pass_rate"] is not None]
    full = [r for r in measured if r["pass_rate"] == 100.0]
    failing = [r for r in measured if r["pass_rate"] == 0.0]
    mixed = [r for r in measured if 0.0 < r["pass_rate"] < 100.0]
    na = [r for r in rows if r["pass_rate"] is None]
    mean_pass = (round(sum(r["pass_rate"] for r in measured) / len(measured), 1)
                 if measured else 0.0)
    coverage_pct = round(len(measured) / len(rows) * 100, 1) if rows else 0.0

    print("\n" + "=" * 72)
    print("MCP CONFORMANCE MATRIX — SUMMARY")
    print("=" * 72)
    print(f"Cases: {len(rows)}  (measured: {len(measured)}, "
          f"N/A all-skipped: {len(na)})")
    print(f"Mean pass rate (measured cases): {mean_pass}%")

    def section(title, items):
        print(f"\n----- {title} ({len(items)}) -----")
        for r in items:
            print(f"  {r['case_id']}  {r['name']:<40} {r['pass_rate']:.1f}%  "
                  f"[{r['level']}]")
        if not items:
            print("  (none)")

    section("Fully conformant — 100% pass rate", full)
    section("Universally failing — 0% pass rate", failing)
    section("Mixed results — partial pass rate", mixed)

    if na:
        print(f"\n----- N/A (all skipped — HTTP-only on STDIO survey) "
              f"({len(na)}) -----")
        for r in na:
            print(f"  {r['case_id']}  {r['name']:<40} [{r['level']}]")

    print(f"\nOverall empirical spec coverage: {len(measured)}/{len(rows)} "
          f"cases measured on >=1 server = {coverage_pct}%")
    print("=" * 72 + "\n")


def main():
    print("Determining transport-gated (HTTP-only) cases via STDIO baseline...")
    try:
        transport_skipped = stdio_baseline_skips()
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] STDIO baseline unavailable ({exc}); "
              "falling back to no transport-skip attribution.")
        transport_skipped = set()
    print(f"  transport-skipped cases: "
          f"{sorted(transport_skipped) or '(none)'}")

    tested = load_tested_servers()
    rows = build_matrix(tested, transport_skipped)

    write_csv(rows)
    HTML_OUT.write_text(write_html(rows, tested, transport_skipped),
                        encoding="utf-8")

    print_summary(rows, transport_skipped)
    print(f"CSV matrix written:  {CSV_OUT}")
    print(f"HTML matrix written: {HTML_OUT}")


if __name__ == "__main__":
    main()
