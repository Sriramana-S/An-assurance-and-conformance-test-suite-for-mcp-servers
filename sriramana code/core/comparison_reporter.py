"""
Comparative compliance report generator for multiple MCP servers.
Produces JSON, HTML, and CSV reports with visual comparisons.
Includes failure analysis, recommendations, and optional benchmark integration.
"""
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict

from core.batch_runner import BatchTestResults, EndpointTestResult
from core.unified_reporter import RecommendationEngine, FailureAnalyzer


class ComparisonReportGenerator:
    """Generates comparative compliance reports with enhanced analysis."""

    def __init__(self, batch_results: BatchTestResults):
        """
        Initialize report generator.

        Args:
            batch_results: BatchTestResults from batch testing
        """
        self.batch_results = batch_results
        self.recommender = RecommendationEngine()
        self.analyzer = FailureAnalyzer()

    def generate_json_report(self, output_file: Path) -> None:
        """
        Generate JSON comparison report with enhanced analysis.

        Args:
            output_file: Output file path
        """
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Collect recommendations for each endpoint
        recommendations_by_server: Dict[str, List] = {}
        for result in self.batch_results.endpoints_tested:
            recommendations_by_server[result.endpoint.name] = \
                self.recommender.generate_compliance_recommendations(result)

        # Collect failure analysis for each endpoint
        failure_analysis_by_server: Dict[str, Dict] = {}
        for result in self.batch_results.endpoints_tested:
            failure_analysis_by_server[result.endpoint.name] = \
                self.analyzer.analyze_failures(result)

        # Get common issues across all servers
        common_issues = self.analyzer.get_common_issues(self.batch_results)

        report = {
            "report_type": "comparative_compliance",
            "report_version": "2.0",
            "generated": datetime.now().isoformat(),
            "summary": {
                "total_endpoints": len(self.batch_results.endpoints_tested),
                "average_score": round(self.batch_results.average_score(), 2),
                "best_performer": self.batch_results.best_performer().endpoint.name if self.batch_results.best_performer() else None,
                "best_score": round(self.batch_results.best_performer().overall_score, 2) if self.batch_results.best_performer() else 0,
                "worst_performer": self.batch_results.worst_performer().endpoint.name if self.batch_results.worst_performer() else None,
                "worst_score": round(self.batch_results.worst_performer().overall_score, 2) if self.batch_results.worst_performer() else 0,
                "duration_seconds": round(self.batch_results.total_duration, 2),
                "total_failures": sum(r.failed_count() for r in self.batch_results.endpoints_tested),
                "total_tests": sum(r.total_count() for r in self.batch_results.endpoints_tested),
            },
            "compliance_comparison": [
                {
                    "endpoint": r.endpoint.name,
                    "url": r.endpoint.url,
                    "overall_score": round(r.overall_score, 2),
                    "protocol_score": round(r.protocol_score, 2),
                    "functional_score": round(r.functional_score, 2),
                    "security_score": round(r.security_score, 2),
                    "passed": r.passed_count(),
                    "failed": r.failed_count(),
                    "total": r.total_count(),
                    "failure_rate_percent": round((r.failed_count() / r.total_count() * 100) if r.total_count() > 0 else 0, 1),
                }
                for r in self.batch_results.endpoints_tested
            ],
            "failure_analysis": {
                "common_failures": [{"test": name, "count": count} for name, count in common_issues[:10]],
                "by_server": failure_analysis_by_server,
            },
            "recommendations": recommendations_by_server,
            "details": self.batch_results.to_dict(),
        }

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)

        print(f"✓ Enhanced JSON report: {output_file}")

    def generate_csv_report(self, output_file: Path) -> None:
        """
        Generate CSV comparison report.

        Args:
            output_file: Output file path
        """
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            # Header
            writer.writerow([
                "Endpoint",
                "URL",
                "Overall Score",
                "Protocol Score",
                "Functional Score",
                "Security Score",
                "Tests Passed",
                "Tests Failed",
                "Total Tests",
            ])

            # Data rows
            for result in self.batch_results.endpoints_tested:
                writer.writerow([
                    result.endpoint.name,
                    result.endpoint.url,
                    round(result.overall_score, 2),
                    round(result.protocol_score, 2),
                    round(result.functional_score, 2),
                    round(result.security_score, 2),
                    result.passed_count(),
                    result.failed_count(),
                    result.total_count(),
                ])

        print(f"Generated CSV report: {output_file}")

    def generate_html_report(self, output_file: Path) -> None:
        """
        Generate HTML comparison report with charts.

        Args:
            output_file: Output file path
        """
        output_file.parent.mkdir(parents=True, exist_ok=True)

        html_content = self._build_html_report()

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

        print(f"Generated HTML report: {output_file}")

    def _build_html_report(self) -> str:
        """Build HTML report content."""
        endpoint_names = [r.endpoint.name for r in self.batch_results.endpoints_tested]
        overall_scores = [r.overall_score for r in self.batch_results.endpoints_tested]
        protocol_scores = [r.protocol_score for r in self.batch_results.endpoints_tested]
        functional_scores = [r.functional_score for r in self.batch_results.endpoints_tested]
        security_scores = [r.security_score for r in self.batch_results.endpoints_tested]

        return f"""<!DOCTYPE html>
<html>
<head>
    <title>MCP Compliance Comparison Report</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1, h2 {{
            color: #333;
        }}
        .summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }}
        .summary-card {{
            background: #f9f9f9;
            padding: 20px;
            border-radius: 6px;
            border-left: 4px solid #007bff;
        }}
        .summary-card h3 {{
            margin: 0 0 10px 0;
            color: #666;
            font-size: 12px;
            text-transform: uppercase;
        }}
        .summary-card .value {{
            font-size: 28px;
            font-weight: bold;
            color: #333;
        }}
        .chart-container {{
            position: relative;
            margin: 40px 0;
            height: 400px;
        }}
        .comparison-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 30px 0;
        }}
        .comparison-table th {{
            background: #f5f5f5;
            padding: 12px;
            text-align: left;
            border-bottom: 2px solid #ddd;
            font-weight: 600;
        }}
        .comparison-table td {{
            padding: 12px;
            border-bottom: 1px solid #eee;
        }}
        .comparison-table tr:hover {{
            background: #f9f9f9;
        }}
        .score-cell {{
            font-weight: bold;
        }}
        .score-good {{
            color: #28a745;
        }}
        .score-warning {{
            color: #ffc107;
        }}
        .score-danger {{
            color: #dc3545;
        }}
        .failure-section {{
            margin: 30px 0;
        }}
        .failure-item {{
            background: #fff3cd;
            padding: 12px;
            margin: 8px 0;
            border-radius: 4px;
            border-left: 4px solid #ffc107;
        }}
        .timestamp {{
            color: #999;
            font-size: 12px;
            margin-top: 20px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔍 MCP Compliance Comparison Report</h1>
        
        <div class="summary">
            <div class="summary-card">
                <h3>Total Endpoints</h3>
                <div class="value">{len(self.batch_results.endpoints_tested)}</div>
            </div>
            <div class="summary-card">
                <h3>Average Score</h3>
                <div class="value">{self.batch_results.average_score():.1f}%</div>
            </div>
            <div class="summary-card">
                <h3>Best Performer</h3>
                <div class="value">{self.batch_results.best_performer().endpoint.name if self.batch_results.best_performer() else 'N/A'}</div>
            </div>
            <div class="summary-card">
                <h3>Testing Duration</h3>
                <div class="value">{self.batch_results.total_duration:.1f}s</div>
            </div>
        </div>

        <h2>Compliance Scores Comparison</h2>
        <div class="chart-container">
            <canvas id="complianceChart"></canvas>
        </div>

        <h2>Category Scores</h2>
        <div class="chart-container">
            <canvas id="categoryChart"></canvas>
        </div>

        <h2>Compliance Details</h2>
        <table class="comparison-table">
            <tr>
                <th>Endpoint</th>
                <th>Overall Score</th>
                <th>Protocol</th>
                <th>Functional</th>
                <th>Security</th>
                <th>Tests</th>
            </tr>
"""

        for result in self.batch_results.endpoints_tested:
            score_class = self._get_score_class(result.overall_score)
            html_content += f"""            <tr>
                <td><strong>{result.endpoint.name}</strong></td>
                <td class="score-cell {score_class}">{result.overall_score:.1f}%</td>
                <td class="score-cell">{result.protocol_score:.1f}%</td>
                <td class="score-cell">{result.functional_score:.1f}%</td>
                <td class="score-cell">{result.security_score:.1f}%</td>
                <td>{result.passed_count()}/{result.total_count()}</td>
            </tr>
"""

        html_content += """        </table>

        <h2>Failure Analysis</h2>
"""

        if self.batch_results.common_failures():
            html_content += "<h3>Common Failures (across multiple endpoints)</h3>\n"
            for failure, count in list(self.batch_results.common_failures().items())[:10]:
                html_content += f'            <div class="failure-item">{failure} <strong>({count} endpoints)</strong></div>\n'

        if self.batch_results.unique_failures():
            html_content += "<h3>Unique Failures (single endpoint)</h3>\n"
            for failure, count in self.batch_results.unique_failures().items():
                html_content += f'            <div class="failure-item">{failure}</div>\n'

        html_content += f"""
        <div class="timestamp">Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
    </div>

    <script>
        // Compliance scores chart
        const ctx1 = document.getElementById('complianceChart').getContext('2d');
        new Chart(ctx1, {{
            type: 'bar',
            data: {{
                labels: {json.dumps(endpoint_names)},
                datasets: [{{
                    label: 'Overall Compliance Score',
                    data: {json.dumps(overall_scores)},
                    backgroundColor: 'rgba(0, 123, 255, 0.6)',
                    borderColor: 'rgba(0, 123, 255, 1)',
                    borderWidth: 1
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                    y: {{
                        beginAtZero: true,
                        max: 100
                    }}
                }}
            }}
        }});

        // Category scores chart
        const ctx2 = document.getElementById('categoryChart').getContext('2d');
        new Chart(ctx2, {{
            type: 'radar',
            data: {{
                labels: {json.dumps(endpoint_names)},
                datasets: [
                    {{
                        label: 'Protocol',
                        data: {json.dumps(protocol_scores)},
                        borderColor: 'rgba(255, 99, 132, 1)',
                        backgroundColor: 'rgba(255, 99, 132, 0.1)'
                    }},
                    {{
                        label: 'Functional',
                        data: {json.dumps(functional_scores)},
                        borderColor: 'rgba(54, 162, 235, 1)',
                        backgroundColor: 'rgba(54, 162, 235, 0.1)'
                    }},
                    {{
                        label: 'Security',
                        data: {json.dumps(security_scores)},
                        borderColor: 'rgba(75, 192, 75, 1)',
                        backgroundColor: 'rgba(75, 192, 75, 0.1)'
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                    r: {{
                        beginAtZero: true,
                        max: 100
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>"""

        return html_content

    @staticmethod
    def _get_score_class(score: float) -> str:
        """Get CSS class for score."""
        if score >= 80:
            return "score-good"
        elif score >= 60:
            return "score-warning"
        else:
            return "score-danger"
