#!/usr/bin/env python
"""
Longitudinal regression tracking for the MCP server survey.

Snapshots survey_results.json over time and compares the two most recent
snapshots to surface regressions (score drops, new MUST violations) and
improvements (score gains, fixed violations), plus servers that appeared or
disappeared between runs.

CLI:
  python longitudinal.py --save      # snapshot current survey_results.json
  python longitudinal.py --compare   # diff the two most recent snapshots
  python longitudinal.py --list      # list all saved snapshots
"""
import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from core.suite import DEFAULT_CASES

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

SURVEY_RESULTS = Path("reports/survey/survey_results.json")
SNAP_DIR = Path("reports/longitudinal")
REG_JSON = SNAP_DIR / "regression_report.json"
REG_HTML = SNAP_DIR / "regression_report.html"

# MUST-level case names (to classify which failed tests are MUST violations).
MUST_TESTS = {c.name for c in DEFAULT_CASES if c.conformance_level == "MUST"}


def _snapshots():
    """All snapshot files, oldest first (timestamped names sort chronologically)."""
    return sorted(SNAP_DIR.glob("snapshot_*.json"))


def save_snapshot():
    if not SURVEY_RESULTS.exists():
        raise SystemExit(f"No survey results to snapshot at {SURVEY_RESULTS}")
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = SNAP_DIR / f"snapshot_{stamp}.json"
    # Guarantee a distinct file even if two saves land in the same second.
    n = 1
    while target.exists():
        target = SNAP_DIR / f"snapshot_{stamp}_{n}.json"
        n += 1
    shutil.copyfile(SURVEY_RESULTS, target)
    print(f"Saved snapshot: {target}")
    return target


def list_snapshots():
    snaps = _snapshots()
    if not snaps:
        print("No snapshots found in", SNAP_DIR)
        return
    print(f"Snapshots in {SNAP_DIR} ({len(snaps)}):")
    for s in snaps:
        try:
            data = json.loads(s.read_text(encoding="utf-8"))
            tested = sum(1 for r in data if r.get("status") == "tested")
            print(f"  {s.name}  ({len(data)} servers, {tested} tested)")
        except Exception:  # noqa: BLE001
            print(f"  {s.name}  (unreadable)")


def _index(records):
    return {r["name"]: r for r in records}


def _must_failures(record):
    return {t for t in record.get("failed_tests", []) if t in MUST_TESTS}


def compare_snapshots():
    snaps = _snapshots()
    if len(snaps) < 2:
        raise SystemExit("Need at least two snapshots to compare "
                         "(run --save twice first).")
    old_path, new_path = snaps[-2], snaps[-1]
    old = _index(json.loads(old_path.read_text(encoding="utf-8")))
    new = _index(json.loads(new_path.read_text(encoding="utf-8")))

    old_names, new_names = set(old), set(new)
    common = old_names & new_names

    score_drops, improvements = [], []
    score_comparison = []  # every server tested in BOTH snapshots
    unchanged = 0
    new_must_violations, fixed_must_violations = [], []
    for name in sorted(common):
        o, n = old[name], new[name]
        if o.get("status") == "tested" and n.get("status") == "tested":
            delta = round(n["score"] - o["score"], 2)
            row = {"name": name, "old_score": o["score"],
                   "new_score": n["score"], "delta": delta}
            score_comparison.append(row)
            if delta < 0:
                score_drops.append(row)
            elif delta > 0:
                improvements.append(row)
            else:
                unchanged += 1
        o_must, n_must = _must_failures(o), _must_failures(n)
        for t in sorted(n_must - o_must):
            new_must_violations.append({"server": name, "test": t})
        for t in sorted(o_must - n_must):
            fixed_must_violations.append({"server": name, "test": t})

    new_servers = sorted(new_names - old_names)
    missing_servers = sorted(old_names - new_names)
    report = {
        "snapshot_old": old_path.name,
        "snapshot_new": new_path.name,
        "score_drops": score_drops,
        "improvements": improvements,
        "new_servers": new_servers,
        "missing_servers": missing_servers,
        "new_must_violations": new_must_violations,
        "fixed_must_violations": fixed_must_violations,
        # Chart inputs.
        "score_comparison": score_comparison,
        "change_summary": {
            "improved": len(improvements),
            "dropped": len(score_drops),
            "unchanged": unchanged,
            "new": len(new_servers),
            "missing": len(missing_servers),
        },
    }

    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    REG_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    REG_HTML.write_text(_render_html(report), encoding="utf-8")
    _print_report(report)
    print(f"\nJSON report: {REG_JSON}")
    print(f"HTML report: {REG_HTML}")
    return report


def _print_report(r):
    print("\n" + "=" * 70)
    print("LONGITUDINAL REGRESSION REPORT")
    print("=" * 70)
    print(f"Comparing:  {r['snapshot_old']}  ->  {r['snapshot_new']}")
    print(f"Score drops:           {len(r['score_drops'])}")
    print(f"Improvements:          {len(r['improvements'])}")
    print(f"New servers:           {len(r['new_servers'])}")
    print(f"Missing servers:       {len(r['missing_servers'])}")
    print(f"New MUST violations:   {len(r['new_must_violations'])}")
    print(f"Fixed MUST violations: {len(r['fixed_must_violations'])}")

    def section(title, rows, fmt):
        if rows:
            print(f"\n----- {title} -----")
            for row in rows:
                print("  " + fmt(row))

    section("Score drops (REGRESSION)", r["score_drops"],
            lambda x: f"{x['name']}: {x['old_score']}% -> {x['new_score']}% ({x['delta']})")
    section("Improvements", r["improvements"],
            lambda x: f"{x['name']}: {x['old_score']}% -> {x['new_score']}% (+{x['delta']})")
    section("New servers", r["new_servers"], lambda x: x)
    section("Missing servers", r["missing_servers"], lambda x: x)
    section("New MUST violations", r["new_must_violations"],
            lambda x: f"{x['server']} :: {x['test']}")
    section("Fixed MUST violations", r["fixed_must_violations"],
            lambda x: f"{x['server']} :: {x['test']}")
    if not any([r["score_drops"], r["improvements"], r["new_servers"],
                r["missing_servers"], r["new_must_violations"],
                r["fixed_must_violations"]]):
        print("\nNo changes between snapshots - identical results.")
    print("=" * 70 + "\n")


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _shorten(name, width=15):
    """Compact a server name for chart x-axis labels."""
    name = str(name)
    return name if len(name) <= width else name[: width - 1] + "…"


def _render_html(r):
    def rows_scores(rows, sign):
        return "".join(
            f"<tr><td>{_esc(x['name'])}</td><td class='num'>{x['old_score']}%</td>"
            f"<td class='num'>{x['new_score']}%</td>"
            f"<td class='num'>{sign}{x['delta']}</td></tr>" for x in rows
        ) or "<tr><td colspan='4'>none</td></tr>"

    def rows_list(items):
        return "".join(f"<li>{_esc(i)}</li>" for i in items) or "<li>none</li>"

    def rows_viol(items):
        return "".join(
            f"<li>{_esc(i['server'])} &mdash; <span class='mono'>{_esc(i['test'])}</span></li>"
            for i in items) or "<li>none</li>"

    # Chart 1 — per-server score comparison (snapshot 1 vs snapshot 2).
    sc = r.get("score_comparison", [])
    chart_labels = [_shorten(x["name"]) for x in sc]
    chart_old = [x["old_score"] for x in sc]
    chart_new = [x["new_score"] for x in sc]
    # Snapshot-2 bar colour: green improved, red dropped, slate unchanged.
    chart_new_colors = [
        "#34d399" if x["delta"] > 0 else "#f87171" if x["delta"] < 0
        else "#64748b"
        for x in sc
    ]

    # Chart 2 — change-summary donut.
    cs = r.get("change_summary", {})
    donut_data = [
        cs.get("improved", 0), cs.get("dropped", 0), cs.get("unchanged", 0),
        cs.get("new", 0), cs.get("missing", 0),
    ]

    repl = {
        "__OLD__": _esc(r["snapshot_old"]),
        "__NEW__": _esc(r["snapshot_new"]),
        "__DROPS_N__": str(len(r["score_drops"])),
        "__IMPR_N__": str(len(r["improvements"])),
        "__NEWSRV_N__": str(len(r["new_servers"])),
        "__MISSRV_N__": str(len(r["missing_servers"])),
        "__NEWVIOL_N__": str(len(r["new_must_violations"])),
        "__FIXVIOL_N__": str(len(r["fixed_must_violations"])),
        "__DROP_ROWS__": rows_scores(r["score_drops"], ""),
        "__IMPR_ROWS__": rows_scores(r["improvements"], "+"),
        "__NEWSRV__": rows_list(r["new_servers"]),
        "__MISSRV__": rows_list(r["missing_servers"]),
        "__NEWVIOL__": rows_viol(r["new_must_violations"]),
        "__FIXVIOL__": rows_viol(r["fixed_must_violations"]),
        "__CHART_LABELS__": json.dumps(chart_labels),
        "__CHART_OLD__": json.dumps(chart_old),
        "__CHART_NEW__": json.dumps(chart_new),
        "__CHART_NEW_COLORS__": json.dumps(chart_new_colors),
        "__DONUT_DATA__": json.dumps(donut_data),
    }
    html = _HTML_TEMPLATE
    for k, v in repl.items():
        html = html.replace(k, v)
    return html


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MCP Longitudinal Regression Report</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:24px;}
  h1{font-size:1.7rem;} h2{color:#93c5fd;margin-top:26px;}
  .meta{color:#94a3b8;margin-bottom:16px;}
  .summary{display:flex;flex-wrap:wrap;gap:16px;}
  .stat{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:12px 20px;}
  .stat .n{font-size:1.6rem;font-weight:700;} .stat .l{color:#94a3b8;font-size:0.75rem;text-transform:uppercase;}
  .drop .n{color:#f87171;} .impr .n{color:#34d399;}
  table{width:100%;border-collapse:collapse;font-size:0.9rem;margin-top:8px;}
  th{text-align:left;background:#334155;padding:7px;} td{padding:6px 8px;border-bottom:1px solid #273449;}
  td.num{text-align:right;font-variant-numeric:tabular-nums;}
  ul{line-height:1.6;} .mono{font-family:monospace;color:#cbd5e1;}
  .charts{display:grid;grid-template-columns:2fr 1fr;gap:24px;margin-top:20px;}
  .chart-card{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:18px;}
  .chart-card canvas{max-height:360px;}
  @media (max-width:900px){.charts{grid-template-columns:1fr;}}
</style></head><body>
<h1>MCP Longitudinal Regression Report</h1>
<div class="meta">Comparing <b>__OLD__</b> &rarr; <b>__NEW__</b></div>
<div class="summary">
  <div class="stat drop"><div class="n">__DROPS_N__</div><div class="l">Score drops</div></div>
  <div class="stat impr"><div class="n">__IMPR_N__</div><div class="l">Improvements</div></div>
  <div class="stat"><div class="n">__NEWSRV_N__</div><div class="l">New servers</div></div>
  <div class="stat"><div class="n">__MISSRV_N__</div><div class="l">Missing servers</div></div>
  <div class="stat drop"><div class="n">__NEWVIOL_N__</div><div class="l">New MUST violations</div></div>
  <div class="stat impr"><div class="n">__FIXVIOL_N__</div><div class="l">Fixed MUST violations</div></div>
</div>
<div class="charts">
  <div class="chart-card"><canvas id="scoreChart"></canvas></div>
  <div class="chart-card"><canvas id="changeChart"></canvas></div>
</div>
<h2>Score Drops (Regressions)</h2>
<table><thead><tr><th>Server</th><th>Old</th><th>New</th><th>Delta</th></tr></thead><tbody>__DROP_ROWS__</tbody></table>
<h2>Improvements</h2>
<table><thead><tr><th>Server</th><th>Old</th><th>New</th><th>Delta</th></tr></thead><tbody>__IMPR_ROWS__</tbody></table>
<h2>New Servers</h2><ul>__NEWSRV__</ul>
<h2>Missing Servers</h2><ul>__MISSRV__</ul>
<h2>New MUST Violations</h2><ul>__NEWVIOL__</ul>
<h2>Fixed MUST Violations</h2><ul>__FIXVIOL__</ul>
<script>
const gridColor = '#334155', tickColor = '#cbd5e1';
// Chart 1 — score comparison (snapshot 1 vs snapshot 2), side-by-side bars.
new Chart(document.getElementById('scoreChart'), {
  type: 'bar',
  data: {
    labels: __CHART_LABELS__,
    datasets: [
      { label: 'Snapshot 1', data: __CHART_OLD__, backgroundColor: '#3b82f6' },
      { label: 'Snapshot 2', data: __CHART_NEW__, backgroundColor: __CHART_NEW_COLORS__ }
    ]
  },
  options: {
    responsive: true,
    plugins: {
      legend: { labels: { color: tickColor } },
      title: { display: true, color: '#e2e8f0', font: { size: 15 },
               text: 'MUST Compliance Score: Snapshot 1 vs Snapshot 2' }
    },
    scales: {
      x: { ticks: { color: tickColor, autoSkip: false, maxRotation: 90, minRotation: 45 }, grid: { color: gridColor } },
      y: { beginAtZero: true, max: 100, ticks: { color: tickColor, callback: v => v + '%' }, grid: { color: gridColor } }
    }
  }
});
// Chart 2 — change-summary donut.
new Chart(document.getElementById('changeChart'), {
  type: 'doughnut',
  data: {
    labels: ['Improved', 'Dropped', 'Unchanged', 'New', 'Missing'],
    datasets: [{
      data: __DONUT_DATA__,
      backgroundColor: ['#34d399', '#f87171', '#64748b', '#3b82f6', '#fbbf24']
    }]
  },
  options: {
    responsive: true,
    plugins: {
      legend: { position: 'bottom', labels: { color: tickColor } },
      title: { display: true, color: '#e2e8f0', font: { size: 15 },
               text: 'Server Conformance Changes Between Snapshots' }
    }
  }
});
</script>
</body></html>"""


def main():
    parser = argparse.ArgumentParser(
        description="Longitudinal regression tracking for the MCP survey.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--save", action="store_true",
                       help="Snapshot the current survey_results.json")
    group.add_argument("--compare", action="store_true",
                       help="Compare the two most recent snapshots")
    group.add_argument("--list", action="store_true",
                       help="List all saved snapshots")
    args = parser.parse_args()

    if args.save:
        save_snapshot()
    elif args.list:
        list_snapshots()
    elif args.compare:
        compare_snapshots()


if __name__ == "__main__":
    main()
