"""
Benchmark report generator for creating visual and data comparisons.
Generates JSON, HTML, and CSV reports with performance analysis.
Includes recommendations and optional compliance integration.
"""
from pathlib import Path
from typing import List, Dict, Optional
import json
import csv
from datetime import datetime

from core.batch_benchmark import BenchmarkComparison
from core.unified_reporter import RecommendationEngine


class BenchmarkReportGenerator:
    """Generates benchmark reports in multiple formats with analysis and recommendations."""
    
    def __init__(self, comparison: BenchmarkComparison):
        """
        Initialize report generator.
        
        Args:
            comparison: BenchmarkComparison to generate reports for
        """
        self.comparison = comparison
        self.recommender = RecommendationEngine()
    
    def generate_json_report(self, output_file: Path) -> None:
        """
        Generate JSON report with enhanced analysis.
        
        Args:
            output_file: Output file path
        """
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Generate recommendations for each server
        recommendations_by_server: Dict[str, List] = {}
        for result in self.comparison.results:
            recommendations_by_server[result.endpoint.name] = \
                self.recommender.generate_performance_recommendations(result)
        
        # Generate comparison recommendations
        comparison_recommendations = \
            self.recommender.generate_comparison_recommendations(self.comparison)
        
        report = {
            "report_type": "benchmark_analysis",
            "report_version": "2.0",
            "benchmark_timestamp": self.comparison.benchmark_timestamp,
            "total_duration_seconds": round(self.comparison.total_duration_seconds, 2),
            "servers_tested": len(self.comparison.results),
            "results": [r.to_dict() for r in self.comparison.results],
            "summary": self._generate_summary(),
            "method_comparison": self._generate_method_comparison(),
            "recommendations": {
                "by_server": recommendations_by_server,
                "comparison": comparison_recommendations,
            },
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        
        print(f"✓ Enhanced JSON report: {output_file}")
    
    def generate_html_report(self, output_file: Path) -> None:
        """
        Generate HTML report with interactive charts.
        
        Args:
            output_file: Output file path
        """
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        summary = self._generate_summary()
        method_comparison = self._generate_method_comparison()
        
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MCP Server Benchmark Report</title>
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
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 10px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            overflow: hidden;
        }}
        header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }}
        header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
        }}
        header .subtitle {{
            font-size: 1.1em;
            opacity: 0.9;
        }}
        .timestamp {{
            font-size: 0.9em;
            opacity: 0.8;
            margin-top: 10px;
        }}
        .content {{
            padding: 30px;
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
        .chart-container {{
            position: relative;
            height: 400px;
            margin-bottom: 40px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
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
        .bar {{
            display: inline-block;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            height: 20px;
            border-radius: 3px;
            margin-left: 10px;
        }}
        .legend {{
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
            margin-top: 20px;
            font-size: 0.95em;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .legend-color {{
            width: 20px;
            height: 20px;
            border-radius: 3px;
        }}
        footer {{
            background: #f8f9fa;
            padding: 20px;
            text-align: center;
            color: #999;
            font-size: 0.9em;
            border-top: 1px solid #e0e0e0;
        }}
        .benchmark-meta {{
            background: #f0f7ff;
            border-left: 4px solid #667eea;
            padding: 15px;
            margin-bottom: 20px;
            border-radius: 4px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🚀 MCP Server Benchmark Report</h1>
            <p class="subtitle">Performance Comparison Across Tested Servers</p>
            <p class="timestamp">Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p class="timestamp">Test Duration: {self.comparison.total_duration_seconds:.1f}s | Servers Tested: {len(self.comparison.results)}</p>
        </header>
        
        <div class="content">
            {self._generate_executive_summary_html(summary)}
            {self._generate_performance_comparison_html(method_comparison)}
            {self._generate_detailed_charts_html()}
            {self._generate_detailed_tables_html()}
        </div>
        
        <footer>
            Generated by MCP Assurance Suite | Benchmark Engine v1.0
        </footer>
    </div>
</body>
</html>"""
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"✓ HTML report: {output_file}")
    
    def generate_csv_report(self, output_file: Path) -> None:
        """
        Generate CSV report for spreadsheet analysis.
        
        Args:
            output_file: Output file path
        """
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        rows = []
        
        # Header rows
        rows.append(["MCP Server Benchmark Results"])
        rows.append(["Generated:", datetime.now().isoformat()])
        rows.append([])
        
        # Server statistics
        rows.append(["Server Name", "Total Requests", "Successful", "Failed", "Success Rate %", 
                    "Avg Response (ms)", "Min (ms)", "Max (ms)", "P95 (ms)", "P99 (ms)", 
                    "Throughput (req/s)"])
        
        for result in self.comparison.results:
            stats = result.get_overall_stats()
            rows.append([
                result.endpoint.name,
                stats.total_requests,
                stats.successful_requests,
                stats.failed_requests,
                f"{stats.success_rate:.1f}",
                f"{stats.avg_response_time:.2f}",
                f"{stats.min_response_time:.2f}",
                f"{stats.max_response_time:.2f}",
                f"{stats.p95_response_time:.2f}",
                f"{stats.p99_response_time:.2f}",
                f"{stats.requests_per_second:.2f}",
            ])
        
        rows.append([])
        rows.append(["Method-Level Statistics"])
        rows.append([])
        
        # Method statistics
        all_methods = set()
        for result in self.comparison.results:
            all_methods.update(result.statistics.keys())
        
        for method in sorted(all_methods):
            rows.append([f"Method: {method}"])
            rows.append(["Server", "Requests", "Avg Response (ms)", "Min (ms)", "Max (ms)", 
                        "P95 (ms)", "P99 (ms)", "Success Rate %"])
            
            for result in self.comparison.results:
                if method in result.statistics:
                    stats = result.statistics[method]
                    rows.append([
                        result.endpoint.name,
                        stats.total_requests,
                        f"{stats.avg_response_time:.2f}",
                        f"{stats.min_response_time:.2f}",
                        f"{stats.max_response_time:.2f}",
                        f"{stats.p95_response_time:.2f}",
                        f"{stats.p99_response_time:.2f}",
                        f"{stats.success_rate:.1f}",
                    ])
            
            rows.append([])
        
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerows(rows)
        
        print(f"✓ CSV report: {output_file}")
    
    def _generate_summary(self) -> dict:
        """Generate summary statistics."""
        summary = {
            "total_servers": len(self.comparison.results),
            "total_requests": sum(
                len(r.metrics) for r in self.comparison.results
            ),
            "total_duration": self.comparison.total_duration_seconds,
        }
        
        fastest = self.comparison.fastest_server()
        slowest = self.comparison.slowest_server()
        best_tp = self.comparison.best_throughput()
        best_sr = self.comparison.highest_success_rate()
        
        if fastest:
            summary["fastest_server"] = fastest.endpoint.name
            summary["fastest_avg_ms"] = round(fastest.get_overall_stats().avg_response_time, 2)
        
        if slowest:
            summary["slowest_server"] = slowest.endpoint.name
            summary["slowest_avg_ms"] = round(slowest.get_overall_stats().avg_response_time, 2)
        
        if best_tp:
            summary["best_throughput_server"] = best_tp.endpoint.name
            summary["best_throughput_rps"] = round(best_tp.get_overall_stats().requests_per_second, 2)
        
        if best_sr:
            summary["best_success_rate_server"] = best_sr.endpoint.name
            summary["best_success_rate_pct"] = round(best_sr.get_overall_stats().success_rate, 1)
        
        return summary
    
    def _generate_method_comparison(self) -> dict:
        """Generate method-level comparison."""
        all_methods = set()
        for result in self.comparison.results:
            all_methods.update(result.statistics.keys())
        
        comparison = {}
        for method in sorted(all_methods):
            comparison[method] = {}
            for result in self.comparison.results:
                if method in result.statistics:
                    stats = result.statistics[method]
                    comparison[method][result.endpoint.name] = {
                        "avg_ms": round(stats.avg_response_time, 2),
                        "min_ms": round(stats.min_response_time, 2),
                        "max_ms": round(stats.max_response_time, 2),
                        "success_rate": round(stats.success_rate, 1),
                        "requests": stats.total_requests,
                    }
        
        return comparison
    
    def _generate_executive_summary_html(self, summary: dict) -> str:
        """Generate HTML executive summary section."""
        fastest = summary.get("fastest_server", "N/A")
        slowest = summary.get("slowest_server", "N/A")
        best_tp = summary.get("best_throughput_server", "N/A")
        
        return f"""
        <div class="section">
            <h2>Executive Summary</h2>
            <div class="benchmark-meta">
                <strong>Overview:</strong> Tested {summary['total_servers']} servers with {summary['total_requests']} total requests in {summary['total_duration']:.1f}s
            </div>
            
            <div class="grid">
                <div class="card highlight">
                    <div class="card-title">🏆 Fastest Server</div>
                    <div class="card-value">{fastest}</div>
                    <div class="card-unit">{summary.get('fastest_avg_ms', 'N/A')}ms avg response</div>
                </div>
                
                <div class="card warning">
                    <div class="card-title">🐢 Slowest Server</div>
                    <div class="card-value">{slowest}</div>
                    <div class="card-unit">{summary.get('slowest_avg_ms', 'N/A')}ms avg response</div>
                </div>
                
                <div class="card">
                    <div class="card-title">⚡ Best Throughput</div>
                    <div class="card-value">{best_tp}</div>
                    <div class="card-unit">{summary.get('best_throughput_rps', 'N/A')} req/s</div>
                </div>
            </div>
        </div>
        """
    
    def _generate_performance_comparison_html(self, method_comparison: dict) -> str:
        """Generate HTML performance comparison section."""
        html = '<div class="section"><h2>Performance by Method</h2>'
        
        for method, servers in sorted(method_comparison.items()):
            html += f'<h3 style="margin-top: 20px; color: #555;">{method}</h3>'
            html += '<table><thead><tr>'
            html += '<th>Server</th><th>Avg (ms)</th><th>Min (ms)</th><th>Max (ms)</th><th>Success %</th><th>Requests</th>'
            html += '</tr></thead><tbody>'
            
            # Sort by average response time
            sorted_servers = sorted(servers.items(), key=lambda x: x[1]['avg_ms'])
            for server, stats in sorted_servers:
                html += f'<tr>'
                html += f'<td><strong>{server}</strong></td>'
                html += f'<td>{stats["avg_ms"]}</td>'
                html += f'<td>{stats["min_ms"]}</td>'
                html += f'<td>{stats["max_ms"]}</td>'
                html += f'<td>{stats["success_rate"]:.1f}%</td>'
                html += f'<td>{stats["requests"]}</td>'
                html += f'</tr>'
            
            html += '</tbody></table>'
        
        html += '</div>'
        return html
    
    def _generate_detailed_charts_html(self) -> str:
        """Generate HTML with detailed charts."""
        servers = [r.endpoint.name for r in self.comparison.results]
        server_json = json.dumps(servers)
        
        avg_times = [r.get_overall_stats().avg_response_time for r in self.comparison.results]
        avg_times_json = json.dumps([round(t, 2) for t in avg_times])
        
        throughputs = [r.get_overall_stats().requests_per_second for r in self.comparison.results]
        throughputs_json = json.dumps([round(t, 2) for t in throughputs])
        
        success_rates = [r.get_overall_stats().success_rate for r in self.comparison.results]
        success_rates_json = json.dumps([round(r, 1) for r in success_rates])
        
        return f"""
        <div class="section">
            <h2>Detailed Performance Charts</h2>
            
            <h3 style="margin-top: 20px; color: #555;">Average Response Time (ms)</h3>
            <div class="chart-container">
                <canvas id="responseTimeChart"></canvas>
            </div>
            
            <h3 style="margin-top: 20px; color: #555;">Throughput (Requests/Second)</h3>
            <div class="chart-container">
                <canvas id="throughputChart"></canvas>
            </div>
            
            <h3 style="margin-top: 20px; color: #555;">Success Rate (%)</h3>
            <div class="chart-container">
                <canvas id="successRateChart"></canvas>
            </div>
            
            <script>
                const servers = {server_json};
                const avgTimes = {avg_times_json};
                const throughputs = {throughputs_json};
                const successRates = {success_rates_json};
                const colors = ['#667eea', '#764ba2', '#f093fb', '#4facfe', '#00f2fe', '#ff6b6b', '#ffd93d', '#6bcf7f'];
                
                // Response Time Chart
                new Chart(document.getElementById('responseTimeChart'), {{
                    type: 'bar',
                    data: {{
                        labels: servers,
                        datasets: [{{
                            label: 'Avg Response Time (ms)',
                            data: avgTimes,
                            backgroundColor: colors.slice(0, servers.length),
                            borderRadius: 5,
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{
                            legend: {{ display: false }}
                        }},
                        scales: {{
                            y: {{ beginAtZero: true }}
                        }}
                    }}
                }});
                
                // Throughput Chart
                new Chart(document.getElementById('throughputChart'), {{
                    type: 'bar',
                    data: {{
                        labels: servers,
                        datasets: [{{
                            label: 'Throughput (req/s)',
                            data: throughputs,
                            backgroundColor: colors.slice(0, servers.length),
                            borderRadius: 5,
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{
                            legend: {{ display: false }}
                        }},
                        scales: {{
                            y: {{ beginAtZero: true }}
                        }}
                    }}
                }});
                
                // Success Rate Chart
                new Chart(document.getElementById('successRateChart'), {{
                    type: 'radar',
                    data: {{
                        labels: servers,
                        datasets: [{{
                            label: 'Success Rate (%)',
                            data: successRates,
                            borderColor: '#667eea',
                            backgroundColor: 'rgba(102, 126, 234, 0.1)',
                            fill: true,
                            pointBackgroundColor: '#667eea',
                            tension: 0.1,
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{
                            legend: {{ display: true }}
                        }},
                        scales: {{
                            r: {{
                                beginAtZero: true,
                                max: 100,
                            }}
                        }}
                    }}
                }});
            </script>
        </div>
        """
    
    def _generate_detailed_tables_html(self) -> str:
        """Generate HTML detailed tables section."""
        html = '<div class="section"><h2>Detailed Statistics</h2>'
        
        for result in self.comparison.results:
            stats = result.get_overall_stats()
            html += f'<h3 style="margin-top: 20px; color: #555;">{result.endpoint.name}</h3>'
            html += f'<table><tbody>'
            html += f'<tr><td><strong>Total Requests</strong></td><td>{stats.total_requests}</td></tr>'
            html += f'<tr><td><strong>Successful</strong></td><td>{stats.successful_requests}</td></tr>'
            html += f'<tr><td><strong>Failed</strong></td><td>{stats.failed_requests}</td></tr>'
            html += f'<tr><td><strong>Success Rate</strong></td><td>{stats.success_rate:.1f}%</td></tr>'
            html += f'<tr><td><strong>Avg Response Time</strong></td><td>{stats.avg_response_time:.2f}ms</td></tr>'
            html += f'<tr><td><strong>Min Response Time</strong></td><td>{stats.min_response_time:.2f}ms</td></tr>'
            html += f'<tr><td><strong>Max Response Time</strong></td><td>{stats.max_response_time:.2f}ms</td></tr>'
            html += f'<tr><td><strong>P95 Response Time</strong></td><td>{stats.p95_response_time:.2f}ms</td></tr>'
            html += f'<tr><td><strong>P99 Response Time</strong></td><td>{stats.p99_response_time:.2f}ms</td></tr>'
            html += f'<tr><td><strong>Throughput</strong></td><td>{stats.requests_per_second:.2f} req/s</td></tr>'
            html += f'</tbody></table>'
        
        html += '</div>'
        return html
