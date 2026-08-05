"""
Unified report generator combining compliance testing and benchmark results.
Produces comprehensive reports with analysis, recommendations, and insights.
"""
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import json
from datetime import datetime

from core.batch_runner import BatchTestResults, EndpointTestResult
from core.batch_benchmark import BenchmarkComparison, ServerBenchmarkResult


# Per-violation remediation hints, keyed by AssuranceResult.test name.
# Each value is a (remediation_hint, correct_response_example) tuple, where the
# example is a compact JSON string showing exactly what a conformant response
# to that malformed input looks like.
REMEDIATION_HINTS = {
    "Empty Method Rejection": (
        "Validate that the method field is a non-empty string before dispatching.",
        '{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"Invalid Request"}}',
    ),
    "Null Method Rejection": (
        "Reject requests where method is null with INVALID_REQUEST (-32600).",
        '{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"Invalid Request"}}',
    ),
    "Invalid Method Type Rejection": (
        "Ensure method is a string type; reject numeric or boolean values.",
        '{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"Invalid Request"}}',
    ),
    "Missing JSON-RPC Version Rejection": (
        "Validate jsonrpc field is present on every incoming request.",
        '{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"Invalid Request"}}',
    ),
    "Invalid JSON-RPC Version Rejection": (
        "Reject requests where jsonrpc is not exactly the string '2.0'.",
        '{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"Invalid Request"}}',
    ),
    "Malformed JSON Parse Error": (
        "Return parse error (-32700) JSON body for all unparseable input.",
        '{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"Parse error"}}',
    ),
    "Non-Object JSON Rejection": (
        "Return INVALID_REQUEST (-32600) when request body is valid JSON but "
        "not an object.",
        '{"jsonrpc":"2.0","id":null,"error":{"code":-32600,"message":"Invalid Request"}}',
    ),
    "Missing Method Field Rejection": (
        "Return INVALID_REQUEST (-32600) when the method field is absent.",
        '{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"Invalid Request"}}',
    ),
    "Array Params Rejection": (
        "Reject requests where params is an array; MCP requires params to be "
        "an object.",
        '{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"Invalid Request"}}',
    ),
    "Unknown Method Rejection": (
        "Return METHOD_NOT_FOUND (-32601) for any method name the server does "
        "not implement.",
        '{"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"Method not found"}}',
    ),
}

GENERIC_REMEDIATION = (
    "Review the spec clause and ensure the server response matches the "
    "normative requirement."
)
GENERIC_CORRECT_RESPONSE = ""


def _result_field(item, name, default=None):
    """Read a field from an AssuranceResult object OR a result dict (so the
    engine works on live results and on results loaded from a JSON report)."""
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


class RecommendationEngine:
    """Generates actionable recommendations based on test and benchmark data."""

    @staticmethod
    def generate_spec_cited_recommendations(results) -> List[Dict]:
        """Severity-ranked, spec-cited remediation items for every failed or
        warned test.

        Each item carries the test name, spec clause, conformance level, a
        targeted remediation hint, and a severity. Ranking puts MUST failures
        (wrong responses) first, then SHOULD failures, then MUST advisories
        (silent drops), then SHOULD advisories — so the most serious,
        spec-mandated violations surface at the top.
        """
        recommendations = []
        for item in results:
            status = _result_field(item, "status")
            if status not in ("FAIL", "WARN"):
                continue

            test = _result_field(item, "test", "Unknown Test")
            category = _result_field(item, "category", "Uncategorized")
            spec_clause = _result_field(item, "spec_clause", "") or "(no spec clause)"
            level = _result_field(item, "conformance_level", "MUST")
            message = _result_field(item, "message", "")
            entry = REMEDIATION_HINTS.get(test)
            if entry:
                hint, correct_example = entry
            else:
                hint, correct_example = GENERIC_REMEDIATION, GENERIC_CORRECT_RESPONSE

            # Rank/severity: MUST FAIL > SHOULD FAIL > MUST WARN > SHOULD WARN.
            if status == "FAIL" and level == "MUST":
                rank, severity = 0, "critical"
            elif status == "FAIL":
                rank, severity = 1, "high"
            elif level == "MUST":
                rank, severity = 2, "medium"
            else:
                rank, severity = 3, "info"

            recommendations.append({
                "rank": rank,
                "severity": severity,
                "status": status,
                "conformance_level": level,
                "category": category,
                "test": test,
                "spec_clause": spec_clause,
                "remediation": hint,
                "correct_response_example": correct_example,
                "observed": message,
                "title": f"[{level} {status}] {test}",
            })

        recommendations.sort(key=lambda r: (r["rank"], r["test"]))
        return recommendations


    # Canonical ordering of conformance categories for grouped output.
    CATEGORY_ORDER = [
        "Protocol Conformance",
        "Functional Correctness",
        "Basic Security Validation",
        "Advanced Negative Validation",
        "Interoperability",
        "Authorization Conformance",
    ]

    @staticmethod
    def generate_compliance_recommendations(
        result: EndpointTestResult,
    ) -> List[Dict]:
        """Generate compliance recommendations grouped by the conformance
        category (AssuranceResult.category) of each failing/warning finding.

        Findings are organised under their real category heading
        (e.g. "Protocol Conformance", "Functional Correctness") rather than
        matched by substrings in the test name.
        """
        recommendations = []

        findings = [
            t for t in result.test_results
            if _result_field(t, "status") in ("FAIL", "WARN")
        ]

        if not findings:
            recommendations.append({
                "severity": "info",
                "category": "All Categories",
                "title": "All Compliance Tests Passed",
                "description": "Server is fully compliant with MCP specification",
                "action": "Continue monitoring for regressions with regular testing",
            })
            return recommendations

        # Group findings under their AssuranceResult.category.
        by_category: Dict[str, list] = {}
        for finding in findings:
            category = _result_field(finding, "category", "Uncategorized")
            by_category.setdefault(category, []).append(finding)

        ordered_categories = (
            [c for c in RecommendationEngine.CATEGORY_ORDER if c in by_category]
            + [c for c in sorted(by_category) if c not in RecommendationEngine.CATEGORY_ORDER]
        )

        for category in ordered_categories:
            group = by_category[category]
            must_failures = [
                t for t in group
                if _result_field(t, "status") == "FAIL"
                and _result_field(t, "conformance_level", "MUST") == "MUST"
            ]
            warnings = [t for t in group if _result_field(t, "status") == "WARN"]
            severity = "high" if must_failures else "medium"
            recommendations.append({
                "severity": severity,
                "category": category,
                "title": f"{len(group)} finding(s) under {category}",
                "description": (
                    f"{len(must_failures)} MUST violation(s) and "
                    f"{len(warnings)} advisory/ies in '{category}'."
                ),
                "failures": [
                    _result_field(t, "test", "Unknown") for t in group[:5]
                ],
                "action": (
                    "Review the spec clauses for these cases and bring the "
                    "server's responses into conformance."
                ),
            })

        return recommendations
    
    @staticmethod
    def generate_performance_recommendations(
        benchmark_result: ServerBenchmarkResult,
    ) -> List[Dict]:
        """Generate recommendations for performance issues."""
        recommendations = []
        stats = benchmark_result.get_overall_stats()
        
        # Response time analysis
        if stats.avg_response_time > 500:
            recommendations.append({
                "severity": "medium",
                "category": "performance_latency",
                "title": "High Average Response Time",
                "description": f"Average response time is {stats.avg_response_time:.0f}ms, which may impact user experience",
                "metric": f"{stats.avg_response_time:.2f}ms",
                "action": "Profile server code, optimize hot paths, consider caching frequently accessed data",
            })
        
        if stats.p99_response_time > 2000:
            recommendations.append({
                "severity": "high",
                "category": "performance_tail_latency",
                "title": "High P99 Latency",
                "description": f"99th percentile response time is {stats.p99_response_time:.0f}ms, indicating tail latency issues",
                "metric": f"{stats.p99_response_time:.2f}ms",
                "action": "Investigate slow request patterns, improve database queries, implement request prioritization",
            })
        
        # Throughput analysis
        if stats.requests_per_second < 10:
            recommendations.append({
                "severity": "medium",
                "category": "performance_throughput",
                "title": "Low Throughput",
                "description": f"Server handles only {stats.requests_per_second:.1f} req/s, may struggle under load",
                "metric": f"{stats.requests_per_second:.2f} req/s",
                "action": "Increase concurrency, add connection pooling, optimize request processing",
            })
        
        # Success rate analysis
        if stats.success_rate < 100:
            recommendations.append({
                "severity": "high",
                "category": "reliability",
                "title": "Error Rate Detected",
                "description": f"Success rate is {stats.success_rate:.1f}%, indicating {stats.error_rate:.1f}% failure rate",
                "metric": f"{stats.error_rate:.1f}% errors",
                "action": "Investigate error causes, implement better error handling and retry logic",
            })
        elif stats.success_rate >= 99.9:
            recommendations.append({
                "severity": "info",
                "category": "reliability",
                "title": "Excellent Reliability",
                "description": "Server maintains {:.2f}% success rate under testing conditions".format(stats.success_rate),
                "metric": f"{stats.success_rate:.2f}% success",
                "action": "Maintain current error handling practices",
            })
        
        return recommendations
    
    @staticmethod
    def generate_comparison_recommendations(
        comparison: BenchmarkComparison,
        compliance_results: Optional[BatchTestResults] = None,
    ) -> List[Dict]:
        """Generate recommendations based on server comparison."""
        recommendations = []
        
        if len(comparison.results) < 2:
            return recommendations
        
        fastest = comparison.fastest_server()
        slowest = comparison.slowest_server()
        best_tp = comparison.best_throughput()
        
        if fastest and slowest:
            time_diff = slowest.get_overall_stats().avg_response_time - fastest.get_overall_stats().avg_response_time
            ratio = slowest.get_overall_stats().avg_response_time / max(1, fastest.get_overall_stats().avg_response_time)
            
            if ratio > 2:
                recommendations.append({
                    "severity": "medium",
                    "category": "performance_comparison",
                    "title": f"Significant Performance Gap ({ratio:.1f}x)",
                    "description": f"{slowest.endpoint.name} is {ratio:.1f}x slower than {fastest.endpoint.name}",
                    "details": {
                        "fastest": fastest.endpoint.name,
                        "slowest": slowest.endpoint.name,
                        "difference_ms": round(time_diff, 2),
                        "ratio": round(ratio, 2),
                    },
                    "action": "Investigate implementation differences, benchmark optimization opportunities",
                })
        
        if best_tp:
            avg_tp = sum(r.get_overall_stats().requests_per_second for r in comparison.results) / len(comparison.results)
            best_stats = best_tp.get_overall_stats()
            
            if best_stats.requests_per_second > avg_tp * 1.5:
                recommendations.append({
                    "severity": "info",
                    "category": "performance_best_practice",
                    "title": f"Best Performer: {best_tp.endpoint.name}",
                    "description": f"{best_tp.endpoint.name} achieves {best_stats.requests_per_second:.1f} req/s, well above average",
                    "action": "Use as reference for optimization, study implementation patterns",
                })
        
        return recommendations


class FailureAnalyzer:
    """Analyzes and categorizes test failures."""
    
    @staticmethod
    def analyze_failures(
        result: EndpointTestResult,
    ) -> Dict:
        """Analyze test failures in detail."""
        failed_tests = [t for t in result.test_results if t.status != "PASS"]
        
        failure_categories = {
            "protocol_errors": [],
            "timeout_errors": [],
            "validation_errors": [],
            "functional_errors": [],
            "other_errors": [],
        }
        
        for test in failed_tests:
            error_lower = (test.message or "").lower()
            
            if "protocol" in error_lower or "json" in error_lower:
                failure_categories["protocol_errors"].append(test)
            elif "timeout" in error_lower or "time" in error_lower:
                failure_categories["timeout_errors"].append(test)
            elif "validation" in error_lower or "invalid" in error_lower:
                failure_categories["validation_errors"].append(test)
            elif "not found" in error_lower or "not implemented" in error_lower:
                failure_categories["functional_errors"].append(test)
            else:
                failure_categories["other_errors"].append(test)
        
        return {
            "total_failed": len(failed_tests),
            "categories": {
                k: len(v) for k, v in failure_categories.items()
            },
            "by_category": {
                k: [
                    {
                        "test": t.test,
                        "error": t.message,
                    }
                    for t in v
                ]
                for k, v in failure_categories.items() if v
            },
        }
    
    @staticmethod
    def get_common_issues(
        batch_results: BatchTestResults,
    ) -> List[Tuple[str, int]]:
        """Get common failure issues across multiple servers."""
        issue_counts: Dict[str, int] = {}
        
        for result in batch_results.endpoints_tested:
            failed_tests = [t for t in result.test_results if t.status != "PASS"]
            for test in failed_tests:
                issue_key = test.test
                issue_counts[issue_key] = issue_counts.get(issue_key, 0) + 1
        
        # Sort by frequency
        sorted_issues = sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)
        return sorted_issues


class UnifiedReportGenerator:
    """Generates unified reports combining compliance and benchmark data."""
    
    def __init__(
        self,
        compliance_results: Optional[BatchTestResults] = None,
        benchmark_results: Optional[BenchmarkComparison] = None,
    ):
        """
        Initialize unified report generator.
        
        Args:
            compliance_results: Batch compliance test results
            benchmark_results: Batch benchmark results
        """
        self.compliance_results = compliance_results
        self.benchmark_results = benchmark_results
        self.recommender = RecommendationEngine()
        self.analyzer = FailureAnalyzer()
    
    def generate_comprehensive_json_report(self, output_file: Path) -> None:
        """Generate comprehensive JSON report with all data."""
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        report = {
            "report_type": "comprehensive_analysis",
            "generated": datetime.now().isoformat(),
            "includes": {
                "compliance": self.compliance_results is not None,
                "benchmark": self.benchmark_results is not None,
            },
        }
        
        # Add compliance data
        if self.compliance_results:
            report["compliance"] = self._compile_compliance_report()
        
        # Add benchmark data
        if self.benchmark_results:
            report["benchmark"] = self._compile_benchmark_report()
        
        # Add combined analysis
        if self.compliance_results and self.benchmark_results:
            report["integrated_analysis"] = self._compile_integrated_analysis()
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        
        print(f"✓ Comprehensive JSON report: {output_file}")
    
    def generate_comprehensive_html_report(self, output_file: Path) -> None:
        """Generate comprehensive HTML report with all analyses."""
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        compliance_section = ""
        benchmark_section = ""
        recommendations_section = ""
        analysis_section = ""
        
        if self.compliance_results:
            compliance_section = self._generate_compliance_html_section()
        
        if self.benchmark_results:
            benchmark_section = self._generate_benchmark_html_section()
        
        if self.compliance_results or self.benchmark_results:
            recommendations_section = self._generate_recommendations_html_section()
            analysis_section = self._generate_analysis_html_section()
        
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MCP Servers - Comprehensive Analysis Report</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{
            max-width: 1600px;
            margin: 0 auto;
            background: white;
            border-radius: 10px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
            overflow: hidden;
        }}
        header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px;
            text-align: center;
        }}
        header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
        }}
        header .subtitle {{
            font-size: 1.2em;
            opacity: 0.95;
        }}
        .tabs {{
            display: flex;
            background: #f5f5f5;
            border-bottom: 2px solid #ddd;
            flex-wrap: wrap;
        }}
        .tab-button {{
            padding: 15px 30px;
            cursor: pointer;
            background: #f5f5f5;
            border: none;
            font-size: 1em;
            font-weight: 600;
            color: #666;
            transition: all 0.3s ease;
        }}
        .tab-button:hover {{
            background: #e0e0e0;
        }}
        .tab-button.active {{
            background: white;
            color: #667eea;
            border-bottom: 3px solid #667eea;
        }}
        .tab-content {{
            display: none;
            padding: 30px;
        }}
        .tab-content.active {{
            display: block;
        }}
        .section {{
            margin-bottom: 40px;
        }}
        .section h2 {{
            font-size: 1.8em;
            color: #333;
            margin-bottom: 20px;
            border-bottom: 3px solid #667eea;
            padding-bottom: 10px;
        }}
        .section h3 {{
            font-size: 1.3em;
            color: #555;
            margin-top: 25px;
            margin-bottom: 15px;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }}
        .card {{
            background: #f8f9fa;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 20px;
        }}
        .card.highlight {{
            background: #e8f5e9;
            border-color: #4caf50;
        }}
        .card.warning {{
            background: #fff3e0;
            border-color: #ff9800;
        }}
        .card.error {{
            background: #ffebee;
            border-color: #f44336;
        }}
        .card.info {{
            background: #e3f2fd;
            border-color: #2196f3;
        }}
        .card-title {{
            font-weight: 600;
            color: #667eea;
            margin-bottom: 10px;
            font-size: 1.1em;
        }}
        .card-value {{
            font-size: 1.8em;
            font-weight: bold;
            color: #333;
        }}
        .card-unit {{
            font-size: 0.9em;
            color: #999;
            margin-top: 5px;
        }}
        .metric-label {{
            font-size: 0.95em;
            color: #666;
            margin-top: 10px;
        }}
        .recommendation {{
            background: #f5f5f5;
            border-left: 4px solid #667eea;
            padding: 15px;
            margin-bottom: 15px;
            border-radius: 4px;
        }}
        .recommendation.critical {{
            border-left-color: #f44336;
            background: #ffebee;
        }}
        .recommendation.high {{
            border-left-color: #ff9800;
            background: #fff3e0;
        }}
        .recommendation.medium {{
            border-left-color: #ffc107;
            background: #fffde7;
        }}
        .recommendation.info {{
            border-left-color: #2196f3;
            background: #e3f2fd;
        }}
        .rec-title {{
            font-weight: 600;
            color: #333;
            margin-bottom: 5px;
        }}
        .rec-description {{
            font-size: 0.95em;
            color: #666;
            margin-bottom: 8px;
        }}
        .rec-action {{
            font-size: 0.9em;
            color: #667eea;
            font-weight: 500;
            margin-top: 8px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }}
        table th {{
            background: #667eea;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: 600;
        }}
        table td {{
            padding: 12px;
            border-bottom: 1px solid #e0e0e0;
        }}
        table tbody tr:hover {{
            background: #f5f5f5;
        }}
        .chart-container {{
            position: relative;
            height: 400px;
            margin: 30px 0;
        }}
        .severity-badge {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 0.85em;
            font-weight: 600;
            margin-right: 10px;
        }}
        .severity-critical {{
            background: #f44336;
            color: white;
        }}
        .severity-high {{
            background: #ff9800;
            color: white;
        }}
        .severity-medium {{
            background: #ffc107;
            color: #333;
        }}
        .severity-info {{
            background: #2196f3;
            color: white;
        }}
        footer {{
            background: #f8f9fa;
            padding: 20px;
            text-align: center;
            color: #999;
            font-size: 0.9em;
            border-top: 1px solid #e0e0e0;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📊 MCP Servers - Comprehensive Analysis Report</h1>
            <p class="subtitle">Compliance Testing & Performance Benchmarking</p>
            <p style="margin-top: 10px; opacity: 0.9; font-size: 0.95em;">
                Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </p>
        </header>
        
        <div class="tabs">
            {self._generate_tab_buttons()}
        </div>
        
        <div id="compliance-tab" class="tab-content active">
            {compliance_section}
        </div>
        
        <div id="benchmark-tab" class="tab-content">
            {benchmark_section}
        </div>
        
        <div id="recommendations-tab" class="tab-content">
            {recommendations_section}
        </div>
        
        <div id="analysis-tab" class="tab-content">
            {analysis_section}
        </div>
        
        <footer>
            Generated by MCP Assurance Suite | Unified Report v1.0
        </footer>
    </div>
    
    {self._generate_chart_scripts()}
    <script>
        function switchTab(tabName) {{
            // Hide all tabs
            document.querySelectorAll('.tab-content').forEach(tab => {{
                tab.classList.remove('active');
            }});
            document.querySelectorAll('.tab-button').forEach(btn => {{
                btn.classList.remove('active');
            }});
            
            // Show selected tab
            document.getElementById(tabName + '-tab').classList.add('active');
            event.target.classList.add('active');
        }}
    </script>
</body>
</html>"""
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"✓ Comprehensive HTML report: {output_file}")
    
    def _compile_compliance_report(self) -> Dict:
        """Compile compliance section data."""
        if not self.compliance_results:
            return {}
        
        common_issues = self.analyzer.get_common_issues(self.compliance_results)
        
        return {
            "summary": {
                "total_endpoints": len(self.compliance_results.endpoints_tested),
                "average_score": round(self.compliance_results.average_score(), 2),
                "best_performer": self.compliance_results.best_performer().endpoint.name if self.compliance_results.best_performer() else None,
                "worst_performer": self.compliance_results.worst_performer().endpoint.name if self.compliance_results.worst_performer() else None,
            },
            "servers": [
                {
                    "name": r.endpoint.name,
                    "url": r.endpoint.url,
                    "overall_score": round(r.overall_score, 2),
                    "protocol_score": round(r.protocol_score, 2),
                    "functional_score": round(r.functional_score, 2),
                    "security_score": round(r.security_score, 2),
                    "passed": r.passed_count(),
                    "failed": r.failed_count(),
                    "total": r.total_count(),
                    "failure_analysis": self.analyzer.analyze_failures(r),
                }
                for r in self.compliance_results.endpoints_tested
            ],
            "common_failures": [
                {"test": name, "frequency": count}
                for name, count in common_issues[:10]
            ],
        }
    
    def _compile_benchmark_report(self) -> Dict:
        """Compile benchmark section data."""
        if not self.benchmark_results:
            return {}
        
        return {
            "summary": {
                "servers_tested": len(self.benchmark_results.results),
                "total_requests": sum(len(r.metrics) for r in self.benchmark_results.results),
                "total_duration": round(self.benchmark_results.total_duration_seconds, 2),
            },
            "rankings": {
                "fastest": self.benchmark_results.fastest_server().endpoint.name if self.benchmark_results.fastest_server() else None,
                "slowest": self.benchmark_results.slowest_server().endpoint.name if self.benchmark_results.slowest_server() else None,
                "best_throughput": self.benchmark_results.best_throughput().endpoint.name if self.benchmark_results.best_throughput() else None,
            },
            "servers": [
                r.to_dict() for r in self.benchmark_results.results
            ],
        }
    
    def _compile_integrated_analysis(self) -> Dict:
        """Compile integrated analysis of both compliance and performance."""
        analysis = {
            "correlation_analysis": {},
            "holistic_scores": {},
        }
        
        # Create a map of endpoints for comparison
        compliance_map = {
            r.endpoint.name: r
            for r in self.compliance_results.endpoints_tested
        } if self.compliance_results else {}
        
        benchmark_map = {
            r.endpoint.name: r
            for r in self.benchmark_results.results
        } if self.benchmark_results else {}
        
        # Analyze correlation between compliance and performance
        for name in compliance_map:
            if name in benchmark_map:
                compliance_score = compliance_map[name].overall_score
                perf_stats = benchmark_map[name].get_overall_stats()
                
                analysis["holistic_scores"][name] = {
                    "compliance_score": round(compliance_score, 2),
                    "avg_response_time": round(perf_stats.avg_response_time, 2),
                    "throughput": round(perf_stats.requests_per_second, 2),
                    "success_rate": round(perf_stats.success_rate, 1),
                    "overall_rating": self._calculate_overall_rating(
                        compliance_score,
                        perf_stats,
                    ),
                }
        
        return analysis
    
    @staticmethod
    def _calculate_overall_rating(
        compliance_score: float,
        perf_stats,
    ) -> str:
        """Calculate overall rating from compliance and performance."""
        compliance_weight = 0.5
        perf_score = min(100, (perf_stats.success_rate * 0.3) + 
                         (min(perf_stats.requests_per_second / 10, 100) * 0.3) +
                         (min(1000 / max(1, perf_stats.avg_response_time), 100) * 0.4))
        
        overall = (compliance_score * compliance_weight) + (perf_score * (1 - compliance_weight))
        
        if overall >= 90:
            return "Excellent"
        elif overall >= 80:
            return "Good"
        elif overall >= 70:
            return "Fair"
        else:
            return "Poor"
    
    def _generate_tab_buttons(self) -> str:
        """Generate HTML tab buttons."""
        buttons = []
        
        if self.compliance_results:
            buttons.append(
                '<button class="tab-button active" onclick="switchTab(\'compliance\')">📋 Compliance</button>'
            )
        
        if self.benchmark_results:
            buttons.append(
                '<button class="tab-button" onclick="switchTab(\'benchmark\')">⚡ Performance</button>'
            )
        
        if self.compliance_results or self.benchmark_results:
            buttons.append(
                '<button class="tab-button" onclick="switchTab(\'recommendations\')">💡 Recommendations</button>'
            )
            buttons.append(
                '<button class="tab-button" onclick="switchTab(\'analysis\')">🔍 Analysis</button>'
            )
        
        return "".join(buttons)
    
    def _generate_compliance_html_section(self) -> str:
        """Generate compliance section HTML."""
        if not self.compliance_results:
            return ""
        
        compliance_data = self._compile_compliance_report()
        servers_html = ""
        
        for server in compliance_data.get("servers", []):
            status_color = "highlight" if server["overall_score"] >= 80 else "warning" if server["overall_score"] >= 60 else "error"
            
            servers_html += f"""
            <div style="margin-bottom: 25px;">
                <h3>{server['name']}</h3>
                <div class="grid">
                    <div class="card {status_color}">
                        <div class="card-title">Overall Score</div>
                        <div class="card-value">{server['overall_score']}/100</div>
                    </div>
                    <div class="card">
                        <div class="card-title">Protocol Compliance</div>
                        <div class="card-value">{server['protocol_score']}/100</div>
                    </div>
                    <div class="card">
                        <div class="card-title">Functional Tests</div>
                        <div class="card-value">{server['functional_score']}/100</div>
                    </div>
                    <div class="card">
                        <div class="card-title">Security</div>
                        <div class="card-value">{server['security_score']}/100</div>
                    </div>
                </div>
                
                <div class="grid">
                    <div class="card highlight">
                        <div class="card-title">Tests Passed</div>
                        <div class="card-value">{server['passed']}</div>
                        <div class="card-unit">of {server['total']} tests</div>
                    </div>
                    <div class="card" style="{'warning' if server['failed'] > 0 else 'highlight'}">
                        <div class="card-title">Tests Failed</div>
                        <div class="card-value">{server['failed']}</div>
                        <div class="card-unit">failure rate: {server['failed']/server['total']*100:.1f}%</div>
                    </div>
                </div>
                
                {self._generate_failure_analysis_html(server)}
            </div>
            """
        
        return f"""
        <div class="section">
            <h2>📋 Compliance Test Results</h2>
            {servers_html}
            
            <h3>Common Failure Patterns</h3>
            <table>
                <thead>
                    <tr>
                        <th>Test Name</th>
                        <th>Frequency (# of servers)</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(f'<tr><td>{item["test"]}</td><td>{item["frequency"]}</td></tr>' 
                    for item in compliance_data.get("common_failures", []))}
                </tbody>
            </table>
        </div>
        """
    
    def _generate_failure_analysis_html(self, server: Dict) -> str:
        """Generate failure analysis HTML for a server."""
        analysis = server.get("failure_analysis", {})
        total_failed = analysis.get("total_failed", 0)
        
        if total_failed == 0:
            return '<p style="color: #4caf50; margin-top: 10px;">✓ No test failures</p>'
        
        by_category = analysis.get("by_category", {})
        html = f'<p style="margin-top: 10px; color: #f44336;">⚠ {total_failed} test failures found:</p>'
        
        for category, failures in by_category.items():
            if failures:
                html += f"<p style='margin-top: 10px; font-weight: 600;'>{category.replace('_', ' ').title()} ({len(failures)})</p>"
                html += "<ul style='margin-left: 20px;'>"
                for failure in failures[:3]:  # Show first 3
                    html += f"<li>{failure['test']}: {failure['error'][:80]}...</li>"
                if len(failures) > 3:
                    html += f"<li><em>... and {len(failures)-3} more</em></li>"
                html += "</ul>"
        
        return html
    
    def _generate_benchmark_html_section(self) -> str:
        """Generate benchmark section HTML."""
        if not self.benchmark_results:
            return ""
        
        benchmark_data = self._compile_benchmark_report()
        
        servers_html = ""
        for result in self.benchmark_results.results:
            stats = result.get_overall_stats()
            servers_html += f"""
            <div style="margin-bottom: 25px;">
                <h3>{result.endpoint.name}</h3>
                <div class="grid">
                    <div class="card">
                        <div class="card-title">Avg Response Time</div>
                        <div class="card-value">{stats.avg_response_time:.2f}ms</div>
                    </div>
                    <div class="card">
                        <div class="card-title">P95 Latency</div>
                        <div class="card-value">{stats.p95_response_time:.2f}ms</div>
                    </div>
                    <div class="card">
                        <div class="card-title">P99 Latency</div>
                        <div class="card-value">{stats.p99_response_time:.2f}ms</div>
                    </div>
                    <div class="card">
                        <div class="card-title">Throughput</div>
                        <div class="card-value">{stats.requests_per_second:.2f}</div>
                        <div class="card-unit">req/s</div>
                    </div>
                    <div class="card {'highlight' if stats.success_rate == 100 else 'error'}">
                        <div class="card-title">Success Rate</div>
                        <div class="card-value">{stats.success_rate:.1f}%</div>
                    </div>
                </div>
            </div>
            """
        
        return f"""
        <div class="section">
            <h2>⚡ Performance Benchmark Results</h2>
            {servers_html}
            
            <h3>Performance Rankings</h3>
            <div class="grid">
                <div class="card highlight">
                    <div class="card-title">🏆 Fastest</div>
                    <div class="card-value">{benchmark_data['rankings']['fastest']}</div>
                </div>
                <div class="card">
                    <div class="card-title">🐢 Slowest</div>
                    <div class="card-value">{benchmark_data['rankings']['slowest']}</div>
                </div>
                <div class="card">
                    <div class="card-title">⚡ Best Throughput</div>
                    <div class="card-value">{benchmark_data['rankings']['best_throughput']}</div>
                </div>
            </div>
        </div>
        """
    
    def _generate_recommendations_html_section(self) -> str:
        """Generate recommendations section HTML."""
        all_recommendations = []
        
        # Collect recommendations from compliance results
        if self.compliance_results:
            for result in self.compliance_results.endpoints_tested:
                recs = self.recommender.generate_compliance_recommendations(result)
                for rec in recs:
                    rec["server"] = result.endpoint.name
                    all_recommendations.extend([rec])
        
        # Collect recommendations from benchmark results
        if self.benchmark_results:
            for result in self.benchmark_results.results:
                recs = self.recommender.generate_performance_recommendations(result)
                for rec in recs:
                    rec["server"] = result.endpoint.name
                    all_recommendations.extend([rec])
        
        # Sort by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "info": 3}
        all_recommendations.sort(key=lambda x: severity_order.get(x.get("severity", "info"), 4))
        
        recommendations_html = ""
        for rec in all_recommendations:
            severity = rec.get("severity", "info")
            action = rec.get("action", "")
            
            recommendations_html += f"""
            <div class="recommendation {severity}">
                <div>
                    <span class="severity-badge severity-{severity}">{severity.upper()}</span>
                    <span style="font-weight: 600;">{rec.get('server', '')}</span>
                </div>
                <div class="rec-title">{rec.get('title', '')}</div>
                <div class="rec-description">{rec.get('description', '')}</div>
                <div class="rec-action">→ {action}</div>
            </div>
            """
        
        return f"""
        <div class="section">
            <h2>💡 Recommendations</h2>
            {recommendations_html}
        </div>
        """
    
    def _generate_analysis_html_section(self) -> str:
        """Generate analysis section HTML."""
        analysis_data = self._compile_integrated_analysis() if (self.compliance_results and self.benchmark_results) else {}
        
        if not analysis_data.get("holistic_scores"):
            return "<div class='section'><h2>🔍 Analysis</h2><p>Analysis requires both compliance and benchmark data.</p></div>"
        
        analysis_html = ""
        for server_name, scores in analysis_data["holistic_scores"].items():
            rating = scores["overall_rating"]
            rating_color = "highlight" if rating in ["Excellent", "Good"] else "warning" if rating == "Fair" else "error"
            
            analysis_html += f"""
            <div style="margin-bottom: 25px;">
                <h3>{server_name}</h3>
                <div class="grid">
                    <div class="card {rating_color}">
                        <div class="card-title">Overall Rating</div>
                        <div class="card-value">{rating}</div>
                    </div>
                    <div class="card">
                        <div class="card-title">Compliance Score</div>
                        <div class="card-value">{scores['compliance_score']}/100</div>
                    </div>
                    <div class="card">
                        <div class="card-title">Avg Response Time</div>
                        <div class="card-value">{scores['avg_response_time']:.2f}ms</div>
                    </div>
                    <div class="card">
                        <div class="card-title">Success Rate</div>
                        <div class="card-value">{scores['success_rate']:.1f}%</div>
                    </div>
                </div>
            </div>
            """
        
        return f"""
        <div class="section">
            <h2>🔍 Integrated Analysis</h2>
            <p>Holistic evaluation combining compliance and performance metrics:</p>
            {analysis_html}
        </div>
        """
    
    def _generate_chart_scripts(self) -> str:
        """Generate JavaScript for charts."""
        return "<script>/* Charts will be rendered here */</script>"
