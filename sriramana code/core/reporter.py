import html
import json
from datetime import datetime
from pathlib import Path

from core.models import AssuranceResult


COMPLIANCE_GROUPS = {
    "protocol": {"Protocol Conformance"},
    "functional": {"Functional Correctness"},
    "security": {
        "Basic Security Validation",
        "Advanced Negative Validation",
    },
    "interoperability": {"Interoperability"},
}


class ReportGenerator:

    def __init__(
        self,
        output_dir="reports",
        target_url=None,
        protocol_version=None,
        transport_type="http",
        transport_metrics=None,
        external_servers=None,
        benchmark_data=None,
    ):
        self.results = []
        self.output_dir = Path(output_dir)
        self.target_url = target_url
        self.protocol_version = protocol_version
        self.transport_type = transport_type
        self.transport_metrics = transport_metrics or {}
        self.external_servers = external_servers or []
        self.benchmark_data = benchmark_data or []
        # Severity-ranked, spec-cited remediation items (set by the caller from
        # the RecommendationEngine). Surfaced in the console, JSON and HTML.
        self.recommendations = []

    def add_result(self, result, status=None, message=None, category="General"):
        if isinstance(result, AssuranceResult):
            self.results.append(result)
            return

        self.results.append(AssuranceResult(
            test=result,
            category=category,
            status=status,
            message=message,
        ))

    def calculate_score(self, results=None):
        results = self.results if results is None else results
        scored_results = [
            result for result in results
            if result.status in ("PASS", "FAIL")
        ]

        passed = sum(
            1 for result in scored_results
            if result.status == "PASS"
        )

        if len(scored_results) == 0:
            return 0

        return round(
            (passed / len(scored_results)) * 100,
            2
        )

    def compliance_scores(self):
        scores = {}

        for group_name, categories in COMPLIANCE_GROUPS.items():
            group_results = [
                result for result in self.results
                if result.category in categories
            ]
            scores[group_name] = {
                "score": self.calculate_score(group_results),
                "passed": sum(
                    1 for result in group_results if result.status == "PASS"
                ),
                "failed": sum(
                    1 for result in group_results if result.status == "FAIL"
                ),
                "skipped": sum(
                    1 for result in group_results if result.status == "SKIP"
                ),
                "total": len(group_results),
                "categories": sorted(categories),
            }

        scores["overall"] = {
            "score": self.calculate_score(),
            **self.summary_counts(),
        }

        return scores

    def summary_counts(self):
        return {
            "passed": sum(1 for result in self.results if result.status == "PASS"),
            "failed": sum(1 for result in self.results if result.status == "FAIL"),
            "warned": sum(1 for result in self.results if result.status == "WARN"),
            "skipped": sum(1 for result in self.results if result.status == "SKIP"),
            "total": len(self.results),
        }

    def conformance_breakdown(self):
        """Spec-level conformance rubric: separate hard MUST violations from
        advisory SHOULD findings, fully passing cases, and skips."""
        return {
            "must_violations": sum(
                1 for result in self.results
                if result.status == "FAIL" and result.conformance_level == "MUST"
            ),
            "should_advisories": sum(
                1 for result in self.results
                if result.status == "WARN" and result.conformance_level == "SHOULD"
            ),
            "passing": sum(
                1 for result in self.results if result.status == "PASS"
            ),
            "skipped": sum(
                1 for result in self.results if result.status == "SKIP"
            ),
        }

    def summary(self):
        return {
            **self.summary_counts(),
            "score": self.calculate_score(),
        }

    def category_summary(self):
        categories = {}
        for result in self.results:
            bucket = categories.setdefault(
                result.category,
                {"PASS": 0, "FAIL": 0, "SKIP": 0},
            )
            bucket[result.status] = bucket.get(result.status, 0) + 1
        return categories

    def server_stability(self):
        """Analyse results for STDIO server stability issues."""
        terminated = any(
            result.evidence.get("server_terminated")
            for result in self.results
            if result.status == "FAIL"
        )
        crash_test = None
        skipped_due_to_crash = 0

        for result in self.results:
            if result.status == "FAIL" and result.evidence.get("server_terminated"):
                crash_test = result.test
            if (
                result.status == "SKIP"
                and "STDIO server terminated" in (result.message or "")
            ):
                skipped_due_to_crash += 1

        if terminated:
            status = "CRASHED"
        elif self.transport_type == "stdio":
            status = "STABLE"
        else:
            status = "N/A"

        return {
            "status": status,
            "transport": self.transport_type,
            "terminated": terminated,
            "crash_test": crash_test,
            "skipped_due_to_crash": skipped_due_to_crash,
        }

    def print_report(self):

        print("\n===== MCP ASSURANCE REPORT =====\n")

        for result in self.results:
            clause = f"  [{result.spec_clause}]" if result.spec_clause else ""
            print(
                f"[{result.status}] ({result.conformance_level}) "
                f"{result.category} / {result.test} -> "
                f"{result.message}{clause}"
            )

        summary = self.summary()
        scores = self.compliance_scores()
        stability = self.server_stability()
        breakdown = self.conformance_breakdown()

        print("\n===============================")
        print(
            f"Overall MUST Compliance Score: {summary['score']}%"
            "  (PASS / (PASS+FAIL); WARN advisories & SKIP excluded)"
        )
        print(f"Protocol Compliance: {scores['protocol']['score']}%")
        print(f"Functional Compliance: {scores['functional']['score']}%")
        print(f"Security Compliance: {scores['security']['score']}%")
        print(f"Interoperability Score: {scores['interoperability']['score']}%")
        print(f"Transport: {self.transport_type}")
        if self.transport_metrics:
            print(
                "Transport Requests: "
                f"{self.transport_metrics.get('request_count', 0)} | "
                "Failures: "
                f"{self.transport_metrics.get('failure_count', 0)} | "
                "Avg Response: "
                f"{self.transport_metrics.get('average_response_time_ms', 0)}ms"
            )
        if stability["status"] != "N/A":
            print(f"Server Stability: {stability['status']}")
            if stability["terminated"]:
                print(f"  Crashed during: {stability['crash_test']}")
                print(
                    f"  Tests skipped due to crash: "
                    f"{stability['skipped_due_to_crash']}"
                )
        print(
            "Passed: {passed} | Failed: {failed} | "
            "Warned: {warned} | Skipped: {skipped}".format(**summary)
        )

        print("\n----- Conformance breakdown -----")
        print(
            f"MUST violations (FAIL on MUST cases):     "
            f"{breakdown['must_violations']}"
        )
        print(
            f"SHOULD advisories (WARN on SHOULD cases): "
            f"{breakdown['should_advisories']}"
        )
        print(f"Fully passing (PASS):                     {breakdown['passing']}")
        print(f"Skipped:                                  {breakdown['skipped']}")

        self.print_recommendations()

    def print_recommendations(self):
        """Print the severity-ranked, spec-cited remediation items."""
        if not self.recommendations:
            return

        must_fail = sum(
            1 for r in self.recommendations
            if r.get("status") == "FAIL" and r.get("conformance_level") == "MUST"
        )
        should_warn = sum(
            1 for r in self.recommendations
            if r.get("status") == "WARN"
        )
        print(
            f"\n----- Recommendations ({len(self.recommendations)}: "
            f"{must_fail} MUST violation(s), {should_warn} advisory/ies) -----"
        )
        for index, rec in enumerate(self.recommendations, 1):
            print(
                f"{index:2}. [{rec['severity'].upper()}] "
                f"({rec['conformance_level']} {rec['status']}) {rec['test']}"
            )
            print(f"    spec:        {rec['spec_clause']}")
            print(f"    remediation: {rec['remediation']}")
            example = rec.get("correct_response_example")
            if example:
                print(f"    correct response: {example}")

    def save_json_report(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        scores = self.compliance_scores()
        stability = self.server_stability()

        report_data = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "target_url": self.target_url,
            "transport_type": self.transport_type,
            "transport_metrics": self.transport_metrics,
            "protocol_version": self.protocol_version,
            "overall_compliance_score": self.calculate_score(),
            "protocol_compliance_score": scores["protocol"]["score"],
            "functional_compliance_score": scores["functional"]["score"],
            "security_compliance_score": scores["security"]["score"],
            "interoperability_score": scores["interoperability"]["score"],
            "server_stability": stability,
            "compliance_scores": scores,
            "summary": self.summary(),
            "category_summary": self.category_summary(),
            "conformance_breakdown": self.conformance_breakdown(),
            "recommendations": self.recommendations,
            "external_servers": self.external_servers,
            "benchmark_comparison": self.benchmark_data,
            "results": [
                {
                    "test": result.test,
                    "category": result.category,
                    "status": result.status,
                    "severity": result.severity,
                    "message": result.message,
                    "evidence": result.evidence,
                    "conformance_level": result.conformance_level,
                    "spec_clause": result.spec_clause,
                }
                for result in self.results
            ]
        }

        output_path = self.output_dir / "compliance_report.json"

        with output_path.open("w", encoding="utf-8") as file:
            json.dump(
                report_data,
                file,
                indent=4
            )

        print(
            "\nJSON report saved: "
            f"{output_path}"
        )

    def save_html_report(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)

        score = self.calculate_score()
        summary = self.summary()
        scores = self.compliance_scores()
        stability = self.server_stability()
        now = datetime.now().isoformat(timespec="seconds")

        # Determine score colour
        if score >= 80:
            score_color = "#2dd4bf"
            score_glow = "rgba(45,212,191,0.4)"
        elif score >= 60:
            score_color = "#fbbf24"
            score_glow = "rgba(251,191,36,0.4)"
        else:
            score_color = "#f87171"
            score_glow = "rgba(248,113,113,0.4)"

        # Stability badge
        if stability["status"] == "CRASHED":
            stability_badge = (
                '<span class="badge badge-fail">CRASHED</span>'
            )
            stability_detail = (
                f'<p class="stability-detail">'
                f'Server process terminated during '
                f'<strong>{html.escape(stability["crash_test"] or "unknown")}'
                f'</strong>. '
                f'{stability["skipped_due_to_crash"]} subsequent test(s) '
                f'were skipped.</p>'
            )
        elif stability["status"] == "STABLE":
            stability_badge = (
                '<span class="badge badge-pass">STABLE</span>'
            )
            stability_detail = (
                '<p class="stability-detail">'
                'Server process remained running throughout all tests.</p>'
            )
        else:
            stability_badge = (
                '<span class="badge badge-skip">N/A</span>'
            )
            stability_detail = (
                '<p class="stability-detail">'
                'Stability tracking applies to STDIO transport only.</p>'
            )

        # Build test rows
        test_rows = ""
        for result in self.results:
            status_lower = result.status.lower()
            test_rows += f"""
            <tr>
                <td>{html.escape(result.category)}</td>
                <td>{html.escape(result.test)}</td>
                <td><span class="badge badge-{status_lower}">{html.escape(result.status)}</span></td>
                <td>{html.escape(result.conformance_level)}</td>
                <td><span class="severity-pill severity-{html.escape(result.severity)}">{html.escape(result.severity)}</span></td>
                <td class="msg-cell">{html.escape(result.message)}</td>
                <td class="mono">{html.escape(result.spec_clause)}</td>
            </tr>"""

        # Build external server summary rows
        external_rows = ""
        if self.external_servers:
            for srv in self.external_servers:
                srv_name = html.escape(str(srv.get("name", "Unknown")))
                srv_url = html.escape(str(srv.get("url", "")))
                srv_score = srv.get("overall_score", 0)
                srv_passed = srv.get("passed", 0)
                srv_failed = srv.get("failed", 0)
                srv_total = srv.get("total", 0)

                if srv_score >= 80:
                    srv_cls = "badge-pass"
                elif srv_score >= 60:
                    srv_cls = "badge-skip"
                else:
                    srv_cls = "badge-fail"

                external_rows += f"""
                <tr>
                    <td><strong>{srv_name}</strong></td>
                    <td class="mono">{srv_url}</td>
                    <td><span class="badge {srv_cls}">{srv_score:.1f}%</span></td>
                    <td>{srv_passed}</td>
                    <td>{srv_failed}</td>
                    <td>{srv_total}</td>
                </tr>"""

        external_section = ""
        if self.external_servers:
            external_section = f"""
            <section class="card" id="external-servers">
                <h2>External Server Summary</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Server</th>
                            <th>URL</th>
                            <th>Score</th>
                            <th>Passed</th>
                            <th>Failed</th>
                            <th>Total</th>
                        </tr>
                    </thead>
                    <tbody>
                        {external_rows}
                    </tbody>
                </table>
            </section>"""

        # Build benchmark comparison table
        benchmark_section = ""
        if self.benchmark_data:
            bench_rows = ""
            for bench in self.benchmark_data:
                b_name = html.escape(str(bench.get("name", "Unknown")))
                b_avg = bench.get("avg_response_ms", 0)
                b_p95 = bench.get("p95_response_ms", 0)
                b_p99 = bench.get("p99_response_ms", 0)
                b_rps = bench.get("requests_per_second", 0)
                b_success = bench.get("success_rate", 0)

                if b_success >= 99:
                    sr_cls = "badge-pass"
                elif b_success >= 90:
                    sr_cls = "badge-skip"
                else:
                    sr_cls = "badge-fail"

                bench_rows += f"""
                <tr>
                    <td><strong>{b_name}</strong></td>
                    <td>{b_avg:.2f}</td>
                    <td>{b_p95:.2f}</td>
                    <td>{b_p99:.2f}</td>
                    <td>{b_rps:.2f}</td>
                    <td><span class="badge {sr_cls}">{b_success:.1f}%</span></td>
                </tr>"""

            benchmark_section = f"""
            <section class="card" id="benchmark-comparison">
                <h2>Benchmark Comparison</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Server</th>
                            <th>Avg (ms)</th>
                            <th>P95 (ms)</th>
                            <th>P99 (ms)</th>
                            <th>Throughput</th>
                            <th>Success</th>
                        </tr>
                    </thead>
                    <tbody>
                        {bench_rows}
                    </tbody>
                </table>
            </section>"""

        # --- Score cards for compliance groups ---
        def _score_card(label, data):
            s = data["score"]
            p = data["passed"]
            f_ = data["failed"]
            sk = data["skipped"]
            if s >= 80:
                cls = "ring-pass"
            elif s >= 60:
                cls = "ring-warn"
            else:
                cls = "ring-fail"
            pct = s / 100 * 251.2
            return f"""
            <div class="score-card">
                <svg viewBox="0 0 100 100" class="ring">
                    <circle cx="50" cy="50" r="40" class="ring-bg"/>
                    <circle cx="50" cy="50" r="40" class="ring-fg {cls}"
                        stroke-dasharray="{pct:.1f} 251.2"/>
                </svg>
                <div class="score-pct">{s}%</div>
                <div class="score-label">{label}</div>
                <div class="score-detail">{p}P / {f_}F / {sk}S</div>
            </div>"""

        score_cards = "".join([
            _score_card("Protocol", scores["protocol"]),
            _score_card("Functional", scores["functional"]),
            _score_card("Security", scores["security"]),
            _score_card("Interop", scores["interoperability"]),
        ])

        # Category summary rows
        cat_rows = ""
        for cat_name, cat_counts in self.category_summary().items():
            cat_total = cat_counts["PASS"] + cat_counts["FAIL"] + cat_counts["SKIP"]
            cat_pct = (
                round(cat_counts["PASS"] / (cat_counts["PASS"] + cat_counts["FAIL"]) * 100, 1)
                if (cat_counts["PASS"] + cat_counts["FAIL"]) > 0
                else 0
            )
            cat_rows += f"""
            <tr>
                <td>{html.escape(cat_name)}</td>
                <td>{cat_counts['PASS']}</td>
                <td>{cat_counts['FAIL']}</td>
                <td>{cat_counts['SKIP']}</td>
                <td>{cat_total}</td>
                <td>{cat_pct}%</td>
            </tr>"""

        # Severity-ranked, spec-cited recommendations
        rec_rows = ""
        for rec in self.recommendations:
            badge = "badge-fail" if rec.get("status") == "FAIL" else "badge-warn"
            example = rec.get('correct_response_example', '')
            example_cell = (
                f"<code class='mono'>{html.escape(example)}</code>"
                if example else "<span class='msg-cell'>&mdash;</span>"
            )
            rec_rows += f"""
            <tr>
                <td><span class="badge {badge}">{html.escape(rec.get('conformance_level',''))} {html.escape(rec.get('status',''))}</span></td>
                <td>{html.escape(rec.get('test',''))}</td>
                <td class="mono">{html.escape(rec.get('spec_clause',''))}</td>
                <td class="msg-cell">{html.escape(rec.get('remediation',''))}</td>
                <td>{example_cell}</td>
            </tr>"""
        rec_section = ""
        if self.recommendations:
            rec_section = f"""
        <section class="card" id="recommendations">
            <h2>Recommendations ({len(self.recommendations)} — MUST violations first)</h2>
            <table>
                <thead>
                    <tr>
                        <th>Level / Status</th>
                        <th>Test</th>
                        <th>Spec Clause</th>
                        <th>Remediation</th>
                        <th>Correct Response Example</th>
                    </tr>
                </thead>
                <tbody>
                    {rec_rows}
                </tbody>
            </table>
        </section>"""

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MCP Assurance Report</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #0f1117;
            --surface: rgba(255,255,255,0.04);
            --border: rgba(255,255,255,0.08);
            --text: #e2e8f0;
            --text-dim: #94a3b8;
            --accent: #667eea;
            --pass: #2dd4bf;
            --fail: #f87171;
            --skip: #fbbf24;
            --warn: #fb923c;
        }}

        * {{ margin:0; padding:0; box-sizing:border-box; }}

        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            line-height: 1.6;
        }}

        .container {{
            max-width: 1280px;
            margin: 0 auto;
            padding: 24px;
        }}

        /* --- Header --- */
        .header {{
            background: linear-gradient(135deg, rgba(102,126,234,0.15) 0%, rgba(118,75,162,0.10) 100%);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 40px;
            margin-bottom: 24px;
            text-align: center;
            backdrop-filter: blur(12px);
        }}
        .header h1 {{
            font-size: 2rem;
            font-weight: 700;
            background: linear-gradient(135deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 8px;
        }}
        .header .subtitle {{ color: var(--text-dim); font-size: 0.95rem; }}

        .hero-score {{
            display: inline-flex;
            flex-direction: column;
            align-items: center;
            margin-top: 24px;
        }}
        .hero-score .big {{
            font-size: 4rem;
            font-weight: 700;
            color: {score_color};
            text-shadow: 0 0 40px {score_glow};
            line-height: 1;
        }}
        .hero-score .label {{
            font-size: 0.85rem;
            color: var(--text-dim);
            margin-top: 4px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}

        .meta-strip {{
            display: flex;
            flex-wrap: wrap;
            gap: 24px;
            justify-content: center;
            margin-top: 20px;
            font-size: 0.85rem;
            color: var(--text-dim);
        }}
        .meta-strip span {{ display: inline-flex; align-items: center; gap: 6px; }}

        /* --- Cards --- */
        .card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 20px;
            backdrop-filter: blur(8px);
        }}
        .card h2 {{
            font-size: 1.25rem;
            font-weight: 600;
            margin-bottom: 16px;
            color: var(--accent);
        }}

        /* --- Score rings --- */
        .scores-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 20px;
        }}
        .score-card {{
            display: flex;
            flex-direction: column;
            align-items: center;
            position: relative;
        }}
        .ring {{ width: 90px; height: 90px; transform: rotate(-90deg); }}
        .ring-bg {{ fill:none; stroke: var(--border); stroke-width:6; }}
        .ring-fg {{
            fill:none; stroke-width:6; stroke-linecap:round;
            transition: stroke-dasharray 1s ease;
        }}
        .ring-pass {{ stroke: var(--pass); }}
        .ring-warn {{ stroke: var(--skip); }}
        .ring-fail {{ stroke: var(--fail); }}
        .score-pct {{
            position: absolute; top: 30px; width: 100%;
            text-align: center; font-size: 1.1rem; font-weight: 700;
        }}
        .score-label {{
            margin-top: 8px;
            font-size: 0.8rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-dim);
        }}
        .score-detail {{ font-size: 0.75rem; color: var(--text-dim); margin-top: 2px; }}

        /* --- Transport / stability strip --- */
        .info-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px;
        }}
        .info-item {{
            background: rgba(255,255,255,0.02);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 14px 18px;
        }}
        .info-item .il {{ font-size: 0.75rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; }}
        .info-item .iv {{ font-size: 1.1rem; font-weight: 600; margin-top: 4px; }}

        /* --- Stability --- */
        .stability-detail {{
            margin-top: 8px;
            font-size: 0.9rem;
            color: var(--text-dim);
        }}

        /* --- Badges --- */
        .badge {{
            display: inline-block;
            padding: 2px 10px;
            border-radius: 6px;
            font-size: 0.8rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .badge-pass {{ background: rgba(45,212,191,0.15); color: var(--pass); }}
        .badge-fail {{ background: rgba(248,113,113,0.15); color: var(--fail); }}
        .badge-warn {{ background: rgba(251,146,60,0.15); color: var(--warn); }}
        .badge-skip {{ background: rgba(251,191,36,0.15); color: var(--skip); }}

        .severity-pill {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 500;
        }}
        .severity-critical {{ background: rgba(248,113,113,0.2); color: #fca5a5; }}
        .severity-high      {{ background: rgba(251,146,60,0.2); color: #fdba74; }}
        .severity-medium     {{ background: rgba(251,191,36,0.2); color: #fde68a; }}
        .severity-low        {{ background: rgba(148,163,184,0.2); color: #cbd5e1; }}

        /* --- Tables --- */
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
        }}
        thead th {{
            text-align: left;
            padding: 10px 12px;
            border-bottom: 2px solid var(--border);
            color: var(--text-dim);
            font-weight: 600;
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        tbody td {{
            padding: 10px 12px;
            border-bottom: 1px solid var(--border);
            vertical-align: top;
        }}
        tbody tr {{ transition: background 0.15s; }}
        tbody tr:hover {{ background: rgba(255,255,255,0.03); }}
        .msg-cell {{ max-width: 400px; word-break: break-word; color: var(--text-dim); font-size: 0.85rem; }}
        .mono {{ font-family: 'Cascadia Code', 'Fira Code', monospace; font-size: 0.82rem; }}

        /* --- Footer --- */
        .footer {{
            text-align: center;
            padding: 24px;
            color: var(--text-dim);
            font-size: 0.8rem;
            border-top: 1px solid var(--border);
            margin-top: 24px;
        }}

        /* --- Animations --- */
        @keyframes fadeIn {{ from {{ opacity:0; transform:translateY(12px); }} to {{ opacity:1; transform:translateY(0); }} }}
        .card, .header {{ animation: fadeIn 0.5s ease forwards; }}
        .card:nth-child(2) {{ animation-delay: 0.1s; }}
        .card:nth-child(3) {{ animation-delay: 0.2s; }}
        .card:nth-child(4) {{ animation-delay: 0.3s; }}

        @media (max-width: 768px) {{
            .container {{ padding: 12px; }}
            .header {{ padding: 24px 16px; }}
            .hero-score .big {{ font-size: 3rem; }}
            .scores-grid {{ grid-template-columns: repeat(2, 1fr); }}
        }}
    </style>
</head>
<body>
    <div class="container">

        <div class="header">
            <h1>MCP Assurance Report</h1>
            <p class="subtitle">Protocol Compliance &amp; Security Validation</p>
            <div class="hero-score">
                <div class="big">{score}%</div>
                <div class="label">Overall MUST Compliance</div>
            </div>
            <div class="meta-strip">
                <span>&#128193; {html.escape(str(self.target_url or "Not specified"))}</span>
                <span>&#128268; {html.escape(str(self.transport_type))}</span>
                <span>&#128196; {html.escape(str(self.protocol_version or "N/A"))}</span>
                <span>&#128197; {now}</span>
            </div>
        </div>

        <!-- Compliance Score Cards -->
        <section class="card" id="compliance-scores">
            <h2>Compliance Scores</h2>
            <div class="scores-grid">
                {score_cards}
            </div>
        </section>

        <!-- Server Stability Status -->
        <section class="card" id="server-stability">
            <h2>Server Stability Status</h2>
            <div class="info-grid">
                <div class="info-item">
                    <div class="il">Status</div>
                    <div class="iv">{stability_badge}</div>
                </div>
                <div class="info-item">
                    <div class="il">Transport</div>
                    <div class="iv">{html.escape(str(self.transport_type))}</div>
                </div>
                <div class="info-item">
                    <div class="il">Requests</div>
                    <div class="iv">{self.transport_metrics.get("request_count", 0)}</div>
                </div>
                <div class="info-item">
                    <div class="il">Transport Failures</div>
                    <div class="iv">{self.transport_metrics.get("failure_count", 0)}</div>
                </div>
                <div class="info-item">
                    <div class="il">Avg Response</div>
                    <div class="iv">{self.transport_metrics.get("average_response_time_ms", 0)}ms</div>
                </div>
            </div>
            {stability_detail}
        </section>

        <!-- Summary by Category -->
        <section class="card" id="category-summary">
            <h2>Results by Category</h2>
            <table>
                <thead>
                    <tr>
                        <th>Category</th>
                        <th>Passed</th>
                        <th>Failed</th>
                        <th>Skipped</th>
                        <th>Total</th>
                        <th>Score</th>
                    </tr>
                </thead>
                <tbody>
                    {cat_rows}
                </tbody>
            </table>
        </section>

        {external_section}

        {benchmark_section}

        <!-- Detailed Test Results -->
        <section class="card" id="test-results">
            <h2>Test Results ({summary['passed']}P / {summary['failed']}F / {summary['skipped']}S)</h2>
            <table>
                <thead>
                    <tr>
                        <th>Category</th>
                        <th>Test</th>
                        <th>Status</th>
                        <th>Level</th>
                        <th>Severity</th>
                        <th>Message</th>
                        <th>Spec Clause</th>
                    </tr>
                </thead>
                <tbody>
                    {test_rows}
                </tbody>
            </table>
        </section>

        {rec_section}

        <div class="footer">
            Generated by MCP Assurance Suite &middot; {now}
        </div>

    </div>
</body>
</html>"""

        output_path = self.output_dir / "compliance_report.html"

        with output_path.open("w", encoding="utf-8") as file:
            file.write(html_content)

        print(
            "HTML report saved: "
            f"{output_path}"
        )
