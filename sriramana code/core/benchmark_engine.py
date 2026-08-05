"""
MCP server benchmarking engine for performance testing and analysis.
Measures response times, throughput, error rates, and other metrics.
"""
import time
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Tuple
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.external_client import ExternalMCPClient, ServerEndpoint
from core.models import ClientResponse


@dataclass
class BenchmarkMetric:
    """Individual benchmark measurement."""
    timestamp: float
    method: str
    response_time_ms: float
    success: bool
    error_message: Optional[str] = None
    payload_size_bytes: int = 0


@dataclass
class BenchmarkStatistics:
    """Statistical analysis of benchmark metrics."""
    method: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    
    # Response times (milliseconds)
    min_response_time: float = 0.0
    max_response_time: float = 0.0
    avg_response_time: float = 0.0
    median_response_time: float = 0.0
    p95_response_time: float = 0.0
    p99_response_time: float = 0.0
    stdev_response_time: float = 0.0
    
    # Throughput (requests per second)
    requests_per_second: float = 0.0
    
    # Error metrics
    error_rate: float = 0.0
    success_rate: float = 0.0
    
    # Data size
    avg_payload_size: int = 0
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "method": self.method,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "response_times_ms": {
                "min": round(self.min_response_time, 2),
                "max": round(self.max_response_time, 2),
                "avg": round(self.avg_response_time, 2),
                "median": round(self.median_response_time, 2),
                "p95": round(self.p95_response_time, 2),
                "p99": round(self.p99_response_time, 2),
                "stdev": round(self.stdev_response_time, 2),
            },
            "throughput": {
                "requests_per_second": round(self.requests_per_second, 2),
            },
            "error_rate": round(self.error_rate, 2),
            "success_rate": round(self.success_rate, 2),
            "avg_payload_size_bytes": self.avg_payload_size,
        }


@dataclass
class ServerBenchmarkResult:
    """Benchmark results for a single server."""
    endpoint: ServerEndpoint
    metrics: List[BenchmarkMetric] = field(default_factory=list)
    statistics: Dict[str, BenchmarkStatistics] = field(default_factory=dict)
    total_duration_seconds: float = 0.0
    benchmark_timestamp: str = ""
    concurrent_requests: int = 1
    requests_per_method: Dict[str, int] = field(default_factory=dict)
    
    def get_overall_stats(self) -> BenchmarkStatistics:
        """Calculate statistics across all methods."""
        if not self.metrics:
            return BenchmarkStatistics("overall")
        
        stats = BenchmarkStatistics("overall")
        stats.total_requests = len(self.metrics)
        stats.successful_requests = sum(1 for m in self.metrics if m.success)
        stats.failed_requests = stats.total_requests - stats.successful_requests
        
        response_times = [m.response_time_ms for m in self.metrics if m.success]
        if response_times:
            stats.min_response_time = min(response_times)
            stats.max_response_time = max(response_times)
            stats.avg_response_time = statistics.mean(response_times)
            stats.median_response_time = statistics.median(response_times)
            if len(response_times) > 1:
                stats.stdev_response_time = statistics.stdev(response_times)
            
            # Calculate percentiles
            sorted_times = sorted(response_times)
            p95_idx = int(len(sorted_times) * 0.95) - 1
            p99_idx = int(len(sorted_times) * 0.99) - 1
            stats.p95_response_time = sorted_times[max(0, p95_idx)]
            stats.p99_response_time = sorted_times[max(0, p99_idx)]
        
        stats.success_rate = (stats.successful_requests / stats.total_requests * 100) if stats.total_requests > 0 else 0
        stats.error_rate = (stats.failed_requests / stats.total_requests * 100) if stats.total_requests > 0 else 0
        stats.requests_per_second = stats.total_requests / self.total_duration_seconds if self.total_duration_seconds > 0 else 0
        
        return stats
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "endpoint": self.endpoint.to_dict(),
            "benchmark_timestamp": self.benchmark_timestamp,
            "total_duration_seconds": round(self.total_duration_seconds, 2),
            "concurrent_requests": self.concurrent_requests,
            "requests_per_method": self.requests_per_method,
            "overall_stats": self.get_overall_stats().to_dict(),
            "method_statistics": {
                method: stats.to_dict()
                for method, stats in self.statistics.items()
            },
            "total_metrics": len(self.metrics),
        }


class ServerBenchmark:
    """Benchmarks a single MCP server."""
    
    def __init__(self, endpoint: ServerEndpoint):
        """
        Initialize benchmark for endpoint.
        
        Args:
            endpoint: ServerEndpoint to benchmark
        """
        self.endpoint = endpoint
        self.client = ExternalMCPClient(endpoint)
        self.metrics: List[BenchmarkMetric] = []
    
    def benchmark_method(
        self,
        method: str,
        params: dict = None,
        iterations: int = 10,
    ) -> BenchmarkStatistics:
        """
        Benchmark a single MCP method.
        
        Args:
            method: MCP method to benchmark
            params: Request parameters
            iterations: Number of iterations
            
        Returns:
            BenchmarkStatistics for this method
        """
        method_metrics = []
        
        for i in range(iterations):
            try:
                start = time.time()
                response = self.client.send_request(
                    method,
                    params=params,
                    request_id=i + 1,
                    retry=False  # No retry for benchmarking accuracy
                )
                elapsed = (time.time() - start) * 1000  # Convert to ms
                
                metric = BenchmarkMetric(
                    timestamp=time.time(),
                    method=method,
                    response_time_ms=elapsed,
                    success=not response.has_transport_error,
                    error_message=response.transport_error if response.has_transport_error else None,
                )
                method_metrics.append(metric)
                self.metrics.append(metric)
                
            except Exception as e:
                metric = BenchmarkMetric(
                    timestamp=time.time(),
                    method=method,
                    response_time_ms=0.0,
                    success=False,
                    error_message=str(e),
                )
                method_metrics.append(metric)
                self.metrics.append(metric)
        
        # Calculate statistics
        stats = BenchmarkStatistics(method)
        stats.total_requests = len(method_metrics)
        stats.successful_requests = sum(1 for m in method_metrics if m.success)
        stats.failed_requests = stats.total_requests - stats.successful_requests
        
        response_times = [m.response_time_ms for m in method_metrics if m.success]
        if response_times:
            stats.min_response_time = min(response_times)
            stats.max_response_time = max(response_times)
            stats.avg_response_time = statistics.mean(response_times)
            stats.median_response_time = statistics.median(response_times)
            if len(response_times) > 1:
                stats.stdev_response_time = statistics.stdev(response_times)
            
            # Calculate percentiles
            sorted_times = sorted(response_times)
            p95_idx = int(len(sorted_times) * 0.95) - 1
            p99_idx = int(len(sorted_times) * 0.99) - 1
            stats.p95_response_time = sorted_times[max(0, p95_idx)]
            stats.p99_response_time = sorted_times[max(0, p99_idx)]
        
        stats.success_rate = (stats.successful_requests / stats.total_requests * 100) if stats.total_requests > 0 else 0
        stats.error_rate = (stats.failed_requests / stats.total_requests * 100) if stats.total_requests > 0 else 0
        
        return stats
    
    def benchmark_methods(
        self,
        methods: List[Tuple[str, dict]] = None,
        iterations_per_method: int = 10,
    ) -> ServerBenchmarkResult:
        """
        Benchmark multiple methods on the server.
        
        Args:
            methods: List of (method_name, params) tuples
            iterations_per_method: Iterations per method
            
        Returns:
            ServerBenchmarkResult with complete benchmark data
        """
        if methods is None:
            methods = [
                ("initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "benchmark", "version": "1.0"}}),
                ("tools/list", {}),
                ("resources/list", {}),
                ("prompts/list", {}),
            ]
        
        result = ServerBenchmarkResult(
            endpoint=self.endpoint,
            benchmark_timestamp=datetime.now().isoformat(),
        )
        
        start_time = time.time()
        
        for method_name, params in methods:
            print(f"  Benchmarking {method_name}...", end=" ", flush=True)
            stats = self.benchmark_method(
                method_name,
                params=params,
                iterations=iterations_per_method,
            )
            result.statistics[method_name] = stats
            result.requests_per_method[method_name] = iterations_per_method
            print(f"✓ {stats.avg_response_time:.2f}ms avg")
        
        result.total_duration_seconds = time.time() - start_time
        result.metrics = self.metrics
        
        return result
    
    def stress_test(
        self,
        method: str = "tools/list",
        duration_seconds: int = 30,
        initial_rps: int = 1,
        max_rps: int = 100,
    ) -> ServerBenchmarkResult:
        """
        Stress test with gradually increasing load.
        
        Args:
            method: Method to stress test
            duration_seconds: Total test duration
            initial_rps: Initial requests per second
            max_rps: Maximum requests per second
            
        Returns:
            ServerBenchmarkResult with stress test data
        """
        result = ServerBenchmarkResult(
            endpoint=self.endpoint,
            benchmark_timestamp=datetime.now().isoformat(),
        )
        
        start_time = time.time()
        current_rps = initial_rps
        request_count = 0
        
        print(f"Stress testing {method} for {duration_seconds}s (RPS: {initial_rps}-{max_rps})")
        
        while time.time() - start_time < duration_seconds:
            # Calculate current RPS based on time
            elapsed = time.time() - start_time
            progress = elapsed / duration_seconds
            current_rps = int(initial_rps + (max_rps - initial_rps) * progress)
            
            # Send requests at current rate
            requests_this_iteration = current_rps // 10  # Send in batches
            for _ in range(requests_this_iteration):
                try:
                    request_start = time.time()
                    response = self.client.send_request(
                        method,
                        params={},
                        request_id=request_count + 1,
                        retry=False,
                    )
                    elapsed_ms = (time.time() - request_start) * 1000
                    
                    metric = BenchmarkMetric(
                        timestamp=time.time(),
                        method=method,
                        response_time_ms=elapsed_ms,
                        success=not response.has_transport_error,
                        error_message=response.transport_error if response.has_transport_error else None,
                    )
                    result.metrics.append(metric)
                    request_count += 1
                    
                except Exception as e:
                    metric = BenchmarkMetric(
                        timestamp=time.time(),
                        method=method,
                        response_time_ms=0.0,
                        success=False,
                        error_message=str(e),
                    )
                    result.metrics.append(metric)
                    request_count += 1
            
            time.sleep(0.1)  # Small delay between iterations
        
        result.total_duration_seconds = time.time() - start_time
        result.requests_per_method[method] = request_count
        result.concurrent_requests = current_rps
        
        # Calculate statistics
        stats = BenchmarkStatistics(method)
        stats.total_requests = len(result.metrics)
        stats.successful_requests = sum(1 for m in result.metrics if m.success)
        stats.failed_requests = stats.total_requests - stats.successful_requests
        
        response_times = [m.response_time_ms for m in result.metrics if m.success]
        if response_times:
            stats.min_response_time = min(response_times)
            stats.max_response_time = max(response_times)
            stats.avg_response_time = statistics.mean(response_times)
            stats.median_response_time = statistics.median(response_times)
            if len(response_times) > 1:
                stats.stdev_response_time = statistics.stdev(response_times)
        
        stats.success_rate = (stats.successful_requests / stats.total_requests * 100) if stats.total_requests > 0 else 0
        stats.error_rate = (stats.failed_requests / stats.total_requests * 100) if stats.total_requests > 0 else 0
        stats.requests_per_second = stats.total_requests / result.total_duration_seconds
        
        result.statistics[method] = stats
        
        return result
