#!/usr/bin/env python
"""
Aggregate analysis of the real-world MCP server survey.

Reads reports/survey/survey_results.json and produces:
  - reports/survey/aggregate_report.json  (statistics)
  - reports/survey/aggregate_report.html  (Chart.js charts + summary table)
  - a console research summary

The survey JSON records per-server failed_tests / warned_tests as *name lists*
only, so spec clauses and categories are looked up from core.suite.DEFAULT_CASES
(the canonical case metadata). MUST-compliance scoring excludes WARN and SKIP
(consistent with the survey's own score = passed / (passed + failed) * 100).
"""
import json
import statistics
import sys
from pathlib import Path

from core.suite import DEFAULT_CASES

try:
    sys.stdout.reconfigure(encoding="utf-8")  # robust on Windows consoles
except Exception:  # noqa: BLE001
    pass

SURVEY_DIR = Path("reports/survey")
RESULTS_PATH = SURVEY_DIR / "survey_results.json"
JSON_OUT = SURVEY_DIR / "aggregate_report.json"
HTML_OUT = SURVEY_DIR / "aggregate_report.html"

# Canonical metadata for every assurance case.
TEST_SPEC_CLAUSE = {c.name: c.spec_clause for c in DEFAULT_CASES}
TEST_CATEGORY = {c.name: c.category for c in DEFAULT_CASES}
CATEGORIES = [
    "Protocol Conformance",
    "Functional Correctness",
    "Basic Security Validation",
    "Advanced Negative Validation",
    "Interoperability",
    "Authorization Conformance",
]

# Categories whose cases are HTTP-transport-only and therefore SKIP on every
# STDIO survey target. The survey JSON records only failed/warned test names
# (no per-test SKIP/PASS), so these categories produce no observable signal in
# a STDIO-only survey and must be reported as N/A rather than a folded 100%.
HTTP_ONLY_CATEGORIES = {"Authorization Conformance"}
SKIPPED_ON_STDIO_LABEL = "N/A (all skipped on STDIO)"
NO_HTTP_LABEL = "N/A (no HTTP servers surveyed)"


def _mean(values):
    return round(statistics.mean(values), 2) if values else 0.0


def _median(values):
    return round(statistics.median(values), 2) if values else 0.0


def _band(score):
    if score <= 20:
        return "0-20"
    if score <= 40:
        return "21-40"
    if score <= 60:
        return "41-60"
    if score <= 80:
        return "61-80"
    return "81-100"


def build_aggregate(results):
    tested = [r for r in results if r["status"] == "tested"]
    n = len(tested)
    scores = [r["score"] for r in tested]

    # Score distribution
    bands = {"0-20": 0, "21-40": 0, "41-60": 0, "61-80": 0, "81-100": 0}
    for s in scores:
        bands[_band(s)] += 1

    # Grouped stats
    def group_stats(key):
        out = {}
        values = sorted(set(r[key] for r in tested))
        for v in values:
            grp = [r["score"] for r in tested if r[key] == v]
            out[v] = {
                "count": len(grp),
                "mean_score": _mean(grp),
                "median_score": _median(grp),
            }
        return out

    by_sdk = group_stats("sdk")
    by_source = group_stats("source")

    # MUST violations by test (failed_tests aggregated across tested servers)
    fail_counts = {}
    for r in tested:
        for t in r["failed_tests"]:
            fail_counts[t] = fail_counts.get(t, 0) + 1
    must_violations_by_test = sorted(
        [
            {
                "test_name": t,
                "spec_clause": TEST_SPEC_CLAUSE.get(t, "(unknown)"),
                "failed_count": c,
                "failure_rate_pct": round(c / n * 100, 1) if n else 0.0,
            }
            for t, c in fail_counts.items()
        ],
        key=lambda x: (-x["failed_count"], x["test_name"]),
    )

    # WARN patterns by test
    warn_counts = {}
    for r in tested:
        for t in r["warned_tests"]:
            warn_counts[t] = warn_counts.get(t, 0) + 1
    warn_patterns_by_test = sorted(
        [
            {
                "test_name": t,
                "spec_clause": TEST_SPEC_CLAUSE.get(t, "(unknown)"),
                "warned_count": c,
                "warn_rate_pct": round(c / n * 100, 1) if n else 0.0,
            }
            for t, c in warn_counts.items()
        ],
        key=lambda x: (-x["warned_count"], x["test_name"]),
    )

    # Pass-or-advisory rate by category: (PASS + WARN) / (PASS + FAIL + WARN).
    # A WARN is an advisory (silent drop, or a SHOULD-level shortfall) and counts
    # as conformant-with-advisory, NOT as a failure. Only a wrong response (FAIL)
    # counts against the rate. Per-test SKIP data is not in the survey JSON, so a
    # category test that is neither failed nor warned is counted as a pass (SKIP
    # folded into pass).
    #
    # HTTP-only categories (Authorization Conformance) only execute on HTTP
    # targets — they SKIP on every STDIO server — so they are measured over the
    # HTTP-transport population alone. On HTTP targets the auth cases never SKIP,
    # so the fold-into-pass rule is exact there. If the survey contains no HTTP
    # servers the category is reported N/A.
    cat_tests = {cat: [c.name for c in DEFAULT_CASES if c.category == cat]
                 for cat in CATEGORIES}
    http_tested = [r for r in tested if r.get("transport") == "http"]
    pass_or_advisory_rate_by_category = {}
    for cat in CATEGORIES:
        names = cat_tests[cat]
        population = http_tested if cat in HTTP_ONLY_CATEGORIES else tested
        passed = failed = warned = 0
        for r in population:
            failed_set = set(r["failed_tests"])
            warned_set = set(r["warned_tests"])
            for name in names:
                if name in failed_set:
                    failed += 1
                elif name in warned_set:
                    warned += 1
                else:
                    passed += 1
        denom = passed + failed + warned
        if denom == 0:
            # An HTTP-only category with no HTTP servers surveyed (or an empty
            # category) is not measurable.
            pass_or_advisory_rate_by_category[cat] = (
                NO_HTTP_LABEL if cat in HTTP_ONLY_CATEGORIES
                else SKIPPED_ON_STDIO_LABEL
            )
        else:
            pass_or_advisory_rate_by_category[cat] = round(
                (passed + warned) / denom * 100, 1
            )

    fully_compliant = sum(1 for r in tested if r["must_violations"] == 0)

    return {
        "total_servers_tested": n,
        "mean_must_score": _mean(scores),
        "median_must_score": _median(scores),
        "score_distribution": bands,
        "by_sdk": by_sdk,
        "by_source": by_source,
        "must_violations_by_test": must_violations_by_test,
        "warn_patterns_by_test": warn_patterns_by_test,
        "pass_or_advisory_rate_by_category": pass_or_advisory_rate_by_category,
        "fully_must_compliant_count": fully_compliant,
        "zero_must_violations_pct": round(fully_compliant / n * 100, 1) if n else 0.0,
    }


def _shorten(name):
    """Compact a test name for chart x-axis labels."""
    for suffix in (" Rejection", " Validation", " Handling", " Schema"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def render_html(agg, results):
    n = agg["total_servers_tested"]

    # Chart 1 - histogram
    hist_labels = list(agg["score_distribution"].keys())
    hist_data = list(agg["score_distribution"].values())
    hist_colors = ["#94a3b8", "#fb7185", "#fbbf24", "#60a5fa", "#34d399"]

    # Chart 2 - top 10 violations
    top = agg["must_violations_by_test"][:10]
    viol_labels = [_shorten(v["test_name"]) for v in top]
    viol_data = [v["failure_rate_pct"] for v in top]

    def viol_color(p):
        if p >= 80:
            return "#ef4444"
        if p >= 40:
            return "#f59e0b"
        return "#eab308"
    viol_colors = [viol_color(p) for p in viol_data]

    # Chart 3 - SDK + source comparison
    sdk = agg["by_sdk"]
    src = agg["by_source"]
    cmp_labels = ["TypeScript", "Python", "Official", "Community"]
    cmp_data = [
        sdk.get("typescript", {}).get("mean_score", 0),
        sdk.get("python", {}).get("mean_score", 0),
        src.get("official", {}).get("mean_score", 0),
        src.get("community", {}).get("mean_score", 0),
    ]
    cmp_colors = ["#3178c6", "#3776ab", "#22c55e", "#a855f7"]

    # Summary table (all servers, sorted by score desc)
    rows = sorted(results, key=lambda r: r["score"], reverse=True)
    table_rows = ""
    for r in rows:
        sc = f"{r['score']:.1f}%" if r["status"] == "tested" else "-"
        status_cls = "ok" if r["status"] == "tested" else "skip"
        table_rows += (
            f"<tr><td>{_esc(r['name'])}</td><td>{r['sdk']}</td>"
            f"<td>{r['source']}</td><td class='num'>{sc}</td>"
            f"<td class='num'>{r['must_violations']}</td>"
            f"<td class='num'>{r['should_advisories']}</td>"
            f"<td class='{status_cls}'>{r['status']}</td></tr>"
        )

    # Pass-or-advisory rate by category
    cat_rate_rows = ""
    for cat, rate in agg["pass_or_advisory_rate_by_category"].items():
        shown = f"{rate}%" if isinstance(rate, (int, float)) else _esc(rate)
        cat_rate_rows += (
            f"<tr><td>{_esc(cat)}</td>"
            f"<td class='num'>{shown}</td></tr>"
        )

    template = _HTML_TEMPLATE
    repl = {
        "__N__": str(n),
        "__MEAN__": str(agg["mean_must_score"]),
        "__MEDIAN__": str(agg["median_must_score"]),
        "__CATEGORY_RATES__": cat_rate_rows,
        "__HIST_LABELS__": json.dumps(hist_labels),
        "__HIST_DATA__": json.dumps(hist_data),
        "__HIST_COLORS__": json.dumps(hist_colors),
        "__VIOL_LABELS__": json.dumps(viol_labels),
        "__VIOL_DATA__": json.dumps(viol_data),
        "__VIOL_COLORS__": json.dumps(viol_colors),
        "__CMP_LABELS__": json.dumps(cmp_labels),
        "__CMP_DATA__": json.dumps(cmp_data),
        "__CMP_COLORS__": json.dumps(cmp_colors),
        "__TABLE_ROWS__": table_rows,
    }
    for k, v in repl.items():
        template = template.replace(k, v)
    return template


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MCP Survey - Aggregate Analysis</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; background:#0f172a; color:#e2e8f0; margin:0; padding:24px; }
  h1 { font-size:1.8rem; } h2 { color:#93c5fd; margin-top:8px; }
  .meta { color:#94a3b8; margin-bottom:20px; }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:24px; }
  .card { background:#1e293b; border:1px solid #334155; border-radius:10px; padding:18px; }
  .full { grid-column:1 / -1; }
  canvas { max-height:340px; }
  table { width:100%; border-collapse:collapse; font-size:0.9rem; margin-top:10px; }
  th { text-align:left; background:#334155; padding:8px; position:sticky; top:0; }
  td { padding:7px 8px; border-bottom:1px solid #334155; }
  td.num { text-align:right; font-variant-numeric:tabular-nums; }
  td.ok { color:#34d399; } td.skip { color:#fbbf24; }
  tbody tr:hover { background:#273449; }
</style>
</head>
<body>
  <h1>MCP Survey &mdash; Aggregate Analysis</h1>
  <div class="meta">n = __N__ tested servers &middot; mean MUST score __MEAN__% &middot; median __MEDIAN__%</div>
  <div class="grid">
    <div class="card"><canvas id="hist"></canvas></div>
    <div class="card"><canvas id="viol"></canvas></div>
    <div class="card full"><canvas id="cmp"></canvas></div>
    <div class="card full">
      <h2>Pass-or-Advisory Rate by Category</h2>
      <p class="meta">pass_or_advisory_rate_by_category = (PASS + WARN) / (PASS + FAIL + WARN) &times; 100 &mdash; a WARN is a silent-drop advisory (conformant-with-advisory), only a wrong response (FAIL) counts against the rate.</p>
      <table>
        <thead><tr><th>Category</th><th>Pass-or-Advisory Rate</th></tr></thead>
        <tbody>__CATEGORY_RATES__</tbody>
      </table>
    </div>
    <div class="card full">
      <h2>Per-Server Summary (sorted by score)</h2>
      <table>
        <thead><tr>
          <th>Server Name</th><th>SDK</th><th>Source</th><th>Score</th>
          <th>MUST Violations</th><th>SHOULD Advisories</th><th>Status</th>
        </tr></thead>
        <tbody>__TABLE_ROWS__</tbody>
      </table>
    </div>
  </div>
<script>
const opts = (title, ymax) => ({
  responsive:true,
  plugins:{ legend:{display:false}, title:{display:true,text:title,color:'#e2e8f0',font:{size:15}} },
  scales:{ x:{ticks:{color:'#cbd5e1'},grid:{color:'#334155'}},
           y:{beginAtZero:true,max:ymax,ticks:{color:'#cbd5e1'},grid:{color:'#334155'}} }
});
new Chart(document.getElementById('hist'), {
  type:'bar',
  data:{ labels:__HIST_LABELS__, datasets:[{ data:__HIST_DATA__, backgroundColor:__HIST_COLORS__ }] },
  options:opts('MUST Compliance Score Distribution (n=__N__)', null)
});
new Chart(document.getElementById('viol'), {
  type:'bar',
  data:{ labels:__VIOL_LABELS__, datasets:[{ data:__VIOL_DATA__, backgroundColor:__VIOL_COLORS__ }] },
  options:opts('Most Violated Spec Clauses (% servers failing)', 100)
});
new Chart(document.getElementById('cmp'), {
  type:'bar',
  data:{ labels:__CMP_LABELS__, datasets:[{ data:__CMP_DATA__, backgroundColor:__CMP_COLORS__ }] },
  options:opts('Mean MUST Compliance by SDK and Source', 100)
});
</script>
</body>
</html>"""


def print_summary(agg):
    print("\n" + "=" * 70)
    print("MCP SURVEY - AGGREGATE RESEARCH SUMMARY")
    print("=" * 70)
    print(f"Total servers tested:        {agg['total_servers_tested']}")
    print(f"Mean MUST score:             {agg['mean_must_score']}%")
    print(f"Median MUST score:           {agg['median_must_score']}%")
    print(f"Fully MUST-compliant:        {agg['fully_must_compliant_count']} "
          f"({agg['zero_must_violations_pct']}%)")

    print("\n----- Score distribution -----")
    for band, count in agg["score_distribution"].items():
        bar = "#" * count
        print(f"  {band:>6}: {count:>2}  {bar}")

    print("\n----- By SDK -----")
    for sdk, d in agg["by_sdk"].items():
        print(f"  {sdk:<11} n={d['count']:<2} mean={d['mean_score']}% median={d['median_score']}%")
    print("----- By source -----")
    for src, d in agg["by_source"].items():
        print(f"  {src:<11} n={d['count']:<2} mean={d['mean_score']}% median={d['median_score']}%")

    print("\n----- Top 5 most-violated spec clauses -----")
    for v in agg["must_violations_by_test"][:5]:
        print(f"  {v['failure_rate_pct']:>5}%  {v['test_name']}")
        print(f"          {v['spec_clause']}")

    print("\n----- Pass-or-advisory rate by category "
          "((PASS+WARN)/(PASS+FAIL+WARN)) -----")
    for cat, rate in agg["pass_or_advisory_rate_by_category"].items():
        shown = f"{rate}%" if isinstance(rate, (int, float)) else str(rate)
        print(f"  {shown:>26}  {cat}")
    print("=" * 70 + "\n")


def main():
    if not RESULTS_PATH.exists():
        raise SystemExit(f"Survey results not found: {RESULTS_PATH}")
    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))

    agg = build_aggregate(results)

    SURVEY_DIR.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(agg, indent=2), encoding="utf-8")
    HTML_OUT.write_text(render_html(agg, results), encoding="utf-8")

    print_summary(agg)
    print(f"JSON report written: {JSON_OUT}")
    print(f"HTML report written: {HTML_OUT}")


if __name__ == "__main__":
    main()
