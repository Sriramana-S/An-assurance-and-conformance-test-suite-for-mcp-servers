#!/usr/bin/env python
"""
Generate shields.io-style SVG conformance badges for the MCP assurance suite.

Two badges are produced (no external service required — the flat SVG is built
directly):

  reports/survey/ecosystem_badge.svg
    Reads reports/survey/aggregate_report.json and shows the ecosystem mean
    MUST-compliance score, e.g. "MCP Conformance | 86.94% ecosystem mean".

  reports/survey/local_badge.svg
    Runs main.py against the bundled local sample server and shows its score,
    e.g. "MCP Conformance | 100.0% local server".

Badge colour: green >= 90%, yellow 70-89%, red < 70%.

CLI:
  python badge_generator.py            # write both SVG badge files
  python badge_generator.py --readme   # print markdown to paste into README
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent
SURVEY_DIR = ROOT / "reports" / "survey"
AGGREGATE_JSON = SURVEY_DIR / "aggregate_report.json"
ECOSYSTEM_SVG = SURVEY_DIR / "ecosystem_badge.svg"
LOCAL_SVG = SURVEY_DIR / "local_badge.svg"

LABEL = "MCP Conformance"

# shields.io standard flat-badge colours.
COLOR_GREEN = "#4c1"
COLOR_YELLOW = "#dfb317"
COLOR_RED = "#e05d44"


def color_for(score: float) -> str:
    """green >= 90, yellow 70-89, red < 70 (so a 100% local score is green)."""
    if score >= 90:
        return COLOR_GREEN
    if score >= 70:
        return COLOR_YELLOW
    return COLOR_RED


def _xml_escape(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _text_width(s: str) -> float:
    """Approximate rendered width (px) of text in Verdana 11px."""
    return len(s) * 6.5


def make_badge(label: str, message: str, color: str) -> str:
    """Build a shields.io flat-style SVG badge (left=grey label, right=colour
    value). Uses the standard scale(.1) text trick for crisp rendering."""
    pad = 6  # horizontal padding (px) on each side of the text
    lw = round(_text_width(label) + 2 * pad)
    rw = round(_text_width(message) + 2 * pad)
    w = lw + rw

    # Positions/lengths in the x10 coordinate space used by transform="scale(.1)".
    label_x = lw * 5  # (lw / 2) * 10
    label_tl = round(_text_width(label) * 10)
    msg_x = round((lw + rw / 2) * 10)
    msg_tl = round(_text_width(message) * 10)

    lab, msg = _xml_escape(label), _xml_escape(message)
    aria = f"{lab}: {msg}"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{w}" height="20" role="img" aria-label="{aria}">
  <title>{aria}</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r"><rect width="{w}" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="{lw}" height="20" fill="#555"/>
    <rect x="{lw}" width="{rw}" height="20" fill="{color}"/>
    <rect width="{w}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" text-rendering="geometricPrecision" font-size="110">
    <text aria-hidden="true" x="{label_x}" y="150" fill="#010101" fill-opacity=".3" transform="scale(.1)" textLength="{label_tl}">{lab}</text>
    <text x="{label_x}" y="140" transform="scale(.1)" textLength="{label_tl}">{lab}</text>
    <text aria-hidden="true" x="{msg_x}" y="150" fill="#010101" fill-opacity=".3" transform="scale(.1)" textLength="{msg_tl}">{msg}</text>
    <text x="{msg_x}" y="140" transform="scale(.1)" textLength="{msg_tl}">{msg}</text>
  </g>
</svg>
"""


def _read_ecosystem_score() -> float:
    if not AGGREGATE_JSON.exists():
        raise SystemExit(
            f"Aggregate report not found: {AGGREGATE_JSON}\n"
            "Run survey_analysis.py first to produce it."
        )
    data = json.loads(AGGREGATE_JSON.read_text(encoding="utf-8"))
    return float(data.get("mean_must_score", 0.0))


def _read_local_score() -> float:
    """Run main.py against the bundled sample server and return its overall
    MUST-compliance score. main.py auto-starts the sample server (the default
    config has use_sample_server=true)."""
    tmp = SURVEY_DIR / "_local_badge_tmp"
    env = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    import os
    env = {**os.environ, **env}
    try:
        subprocess.run(
            [sys.executable, "main.py", "--output-dir", str(tmp)],
            cwd=str(ROOT), env=env, check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        report = json.loads(
            (tmp / "compliance_report.json").read_text(encoding="utf-8"))
        return float(report.get("overall_compliance_score", 0.0))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def generate_badges() -> dict:
    SURVEY_DIR.mkdir(parents=True, exist_ok=True)

    eco_score = _read_ecosystem_score()
    eco_msg = f"{eco_score:.2f}% ecosystem mean"
    ECOSYSTEM_SVG.write_text(
        make_badge(LABEL, eco_msg, color_for(eco_score)), encoding="utf-8")
    print(f"Ecosystem badge written: {ECOSYSTEM_SVG}  "
          f"({eco_msg}, colour {color_for(eco_score)})")

    local_score = _read_local_score()
    local_msg = f"{local_score:.1f}% local server"
    LOCAL_SVG.write_text(
        make_badge(LABEL, local_msg, color_for(local_score)), encoding="utf-8")
    print(f"Local badge written:     {LOCAL_SVG}  "
          f"({local_msg}, colour {color_for(local_score)})")

    return {"ecosystem_score": eco_score, "local_score": local_score}


def _rel(path: Path) -> str:
    """POSIX-style path relative to the project root for markdown links."""
    return path.relative_to(ROOT).as_posix()


def print_readme_markdown():
    print("<!-- MCP conformance badges (regenerate with: "
          "python badge_generator.py) -->")
    print(f"![MCP Ecosystem Conformance]({_rel(ECOSYSTEM_SVG)})")
    print(f"![MCP Local Server Conformance]({_rel(LOCAL_SVG)})")


def main():
    parser = argparse.ArgumentParser(
        description="Generate MCP conformance SVG badges.")
    parser.add_argument(
        "--readme", action="store_true",
        help="Print markdown for both badges (to paste into README).")
    args = parser.parse_args()

    if args.readme:
        print_readme_markdown()
    else:
        generate_badges()


if __name__ == "__main__":
    main()
