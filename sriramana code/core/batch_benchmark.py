"""
Batch benchmarking coordinator for testing multiple MCP servers.
Collects and aggregates performance metrics across servers.
"""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import json

from core.benchmark_engine import ServerBenchmark, ServerBenchmarkResult
from core.external_client import ServerEndpoint


@dataclass
class BenchmarkComparison:
    """Comparison of benchmarks across multiple servers."""
    results: List[ServerBenchmarkResult] = field(default_factory=list)
    benchmark_timestamp: str = ""
    total_duration_seconds: float = 0.0
    
    def fastest_server(self, method: str = None) -> Optional[ServerBenchmarkResult]:
        """Get server with fastest response time."""
        if not self.results:
            return None
        
        if method:
            valid_results = [r for r in self.results if method in r.statistics]
            if not valid_results:
                return None
            return min(valid_results, key=lambda r: r.statistics[method].avg_response_time)
        else:
            return min(self.results, key=lambda r: r.get_overall_stats().avg_response_time)
    
    def slowest_server(self, method: str = None) -> Optional[ServerBenchmarkResult]:
        """Get server with slowest response time."""
        if not self.results:
            return None
        
        if method:
            valid_results = [r for r in self.results if method in r.statistics]
            if not valid_results:
                return None
            return max(valid_results, key=lambda r: r.statistics[method].avg_response_time)
        else:
            return max(self.results, key=lambda r: r.get_overall_stats().avg_response_time)
    
    def best_throughput(self) -> Optional[ServerBenchmarkResult]:
        """Get server with highest throughput."""
        if not self.results:
            return None
        return max(self.results, key=lambda r: r.get_overall_stats().requests_per_second)
    
    def highest_success_rate(self) -> Optional[ServerBenchmarkResult]:
        """Get server with highest success rate."""
        if not self.results:
            return None
        return max(self.results, key=lambda r: r.get_overall_stats().success_rate)
    
    def average_response_time_by_method(self, method: str) -> Dict[str, float]:
        """Get average response time for all servers for a method."""
        result = {}
        for bench_result in self.results:
            if method in bench_result.statistics:
                result[bench_result.endpoint.name] = bench_result.statistics[method].avg_response_time
        return result
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "benchmark_timestamp": self.benchmark_timestamp,
            "total_duration_seconds": round(self.total_duration_seconds, 2),
            "servers_tested": len(self.results),
            "results": [r.to_dict() for r in self.results],
            "rankings": {
                "fastest": self.fastest_server().endpoint.name if self.fastest_server() else None,
                "slowest": self.slowest_server().endpoint.name if self.slowest_server() else None,
                "best_throughput": self.best_throughput().endpoint.name if self.best_throughput() else None,
                "highest_success_rate": self.highest_success_rate().endpoint.name if self.highest_success_rate() else None,
            },
        }


class BatchBenchmarkRunner:
    """Runs benchmarks on multiple MCP servers."""
    
    def __init__(self, endpoints: List[ServerEndpoint]):
        """
        Initialize batch benchmarking runner.
        
        Args:
            endpoints: List of ServerEndpoint configurations
        """
        self.endpoints = endpoints
        self.comparison = BenchmarkComparison()
    
    def run_benchmarks(
        self,
        iterations_per_method: int = 10,
        methods: List[tuple] = None,
    ) -> BenchmarkComparison:
        """
        Run benchmarks on all endpoints.
        
        Args:
            iterations_per_method: Iterations per method per server
            methods: List of (method, params) tuples
            
        Returns:
            BenchmarkComparison with all results
        """
        self.comparison.benchmark_timestamp = datetime.now().isoformat()
        start_time = datetime.now()
        
        print(f"\nBenchmarking {len(self.endpoints)} Servers")
        print("=" * 80)
        
        for i, endpoint in enumerate(self.endpoints, 1):
            print(f"\n[{i}/{len(self.endpoints)}] Benchmarking: {endpoint.name}")
            print(f"  URL: {endpoint.url}")
            
            try:
                benchmark = ServerBenchmark(endpoint)
                result = benchmark.benchmark_methods(
                    methods=methods,
                    iterations_per_method=iterations_per_method,
                )
                self.comparison.results.append(result)
                
                stats = result.get_overall_stats()
                print(f"\n  Results:")
                print(f"    Total Requests: {stats.total_requests}")
                print(f"    Success Rate: {stats.success_rate:.1f}%")
                print(f"    Avg Response Time: {stats.avg_response_time:.2f}ms")
                print(f"    Throughput: {stats.requests_per_second:.2f} req/s")
                
            except Exception as e:
                print(f"  ⚠ Error: {e}")
        
        elapsed = (datetime.now() - start_time).total_seconds()
        self.comparison.total_duration_seconds = elapsed
        
        print("\n" + "=" * 80)
        print("Benchmarking Complete")
        print(f"Total Duration: {elapsed:.1f}s")
        
        # Print rankings
        fastest = self.comparison.fastest_server()
        slowest = self.comparison.slowest_server()
        best_tp = self.comparison.best_throughput()
        
        print("\n🏆 Rankings:")
        if fastest:
            print(f"  Fastest: {fastest.endpoint.name} ({fastest.get_overall_stats().avg_response_time:.2f}ms avg)")
        if slowest:
            print(f"  Slowest: {slowest.endpoint.name} ({slowest.get_overall_stats().avg_response_time:.2f}ms avg)")
        if best_tp:
            print(f"  Best Throughput: {best_tp.endpoint.name} ({best_tp.get_overall_stats().requests_per_second:.2f} req/s)")
        
        return self.comparison
    
    def run_stress_tests(
        self,
        method: str = "tools/list",
        duration_seconds: int = 30,
        initial_rps: int = 1,
        max_rps: int = 100,
    ) -> BenchmarkComparison:
        """
        Run stress tests on all endpoints.
        
        Args:
            method: Method to stress test
            duration_seconds: Test duration per server
            initial_rps: Initial requests per second
            max_rps: Maximum requests per second
            
        Returns:
            BenchmarkComparison with stress test results
        """
        self.comparison.benchmark_timestamp = datetime.now().isoformat()
        start_time = datetime.now()
        
        print(f"\nStress Testing {len(self.endpoints)} Servers ({method})")
        print("=" * 80)
        
        for i, endpoint in enumerate(self.endpoints, 1):
            print(f"\n[{i}/{len(self.endpoints)}] {endpoint.name}")
            
            try:
                benchmark = ServerBenchmark(endpoint)
                result = benchmark.stress_test(
                    method=method,
                    duration_seconds=duration_seconds,
                    initial_rps=initial_rps,
                    max_rps=max_rps,
                )
                self.comparison.results.append(result)
                
                stats = result.get_overall_stats()
                print(f"  ✓ Completed: {stats.total_requests} requests")
                print(f"    Success Rate: {stats.success_rate:.1f}%")
                print(f"    Avg Response: {stats.avg_response_time:.2f}ms")
                print(f"    Throughput: {stats.requests_per_second:.2f} req/s")
                
            except Exception as e:
                print(f"  ⚠ Error: {e}")
        
        elapsed = (datetime.now() - start_time).total_seconds()
        self.comparison.total_duration_seconds = elapsed
        
        print("\n" + "=" * 80)
        print("Stress Testing Complete")
        
        return self.comparison
    
    def save_results_json(self, output_file: Path) -> None:
        """
        Save benchmark results as JSON.
        
        Args:
            output_file: Output file path
        """
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w') as f:
            json.dump(self.comparison.to_dict(), f, indent=2)
        print(f"Saved benchmark results: {output_file}")
    
    def save_individual_results(self, output_dir: Path) -> None:
        """
        Save individual server benchmark results.
        
        Args:
            output_dir: Output directory
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        for result in self.comparison.results:
            filename = f"{result.endpoint.name.lower().replace(' ', '_')}_benchmark.json"
            output_file = output_dir / filename
            with open(output_file, 'w') as f:
                json.dump(result.to_dict(), f, indent=2)
        print(f"Saved {len(self.comparison.results)} individual benchmark results to {output_dir}")
