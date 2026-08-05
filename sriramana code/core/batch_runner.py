"""
Batch runner for testing multiple external MCP servers.
Coordinates sequential testing and collects comparative data.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from core.conformance import ProtocolConformanceEngine
from core.external_client import ExternalMCPClient, ServerEndpoint
from core.models import AssuranceResult
from core.suite import (
    run_initialize_test,
    run_tools_list_test,
    run_resources_list_test,
    run_prompts_list_test,
    run_tool_execution_test,
)


@dataclass
class EndpointTestResult:
    """Test results for a single endpoint."""
    endpoint: ServerEndpoint
    test_results: List[AssuranceResult] = field(default_factory=list)
    protocol_score: float = 0.0
    functional_score: float = 0.0
    security_score: float = 0.0
    overall_score: float = 0.0
    test_timestamp: str = ""
    error_message: Optional[str] = None
    metrics: dict = field(default_factory=dict)

    def passed_count(self) -> int:
        """Count passed tests."""
        return sum(1 for r in self.test_results if r.status == "PASS")

    def failed_count(self) -> int:
        """Count failed tests."""
        return sum(1 for r in self.test_results if r.status == "FAIL")

    def total_count(self) -> int:
        """Total test count."""
        return len(self.test_results)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "endpoint": self.endpoint.to_dict(),
            "test_timestamp": self.test_timestamp,
            "total_tests": self.total_count(),
            "passed": self.passed_count(),
            "failed": self.failed_count(),
            "protocol_score": round(self.protocol_score, 2),
            "functional_score": round(self.functional_score, 2),
            "security_score": round(self.security_score, 2),
            "overall_score": round(self.overall_score, 2),
            "error_message": self.error_message,
            "metrics": self.metrics,
            "test_results": [
                {
                    "name": r.test,
                    "status": r.status,
                    "message": r.message,
                    "category": r.category,
                }
                for r in self.test_results
            ],
        }


@dataclass
class BatchTestResults:
    """Results from testing multiple endpoints."""
    endpoints_tested: List[EndpointTestResult] = field(default_factory=list)
    batch_timestamp: str = ""
    total_duration: float = 0.0

    def best_performer(self) -> Optional[EndpointTestResult]:
        """Get endpoint with highest compliance score."""
        if not self.endpoints_tested:
            return None
        return max(self.endpoints_tested, key=lambda e: e.overall_score)

    def worst_performer(self) -> Optional[EndpointTestResult]:
        """Get endpoint with lowest compliance score."""
        if not self.endpoints_tested:
            return None
        return min(self.endpoints_tested, key=lambda e: e.overall_score)

    def average_score(self) -> float:
        """Calculate average compliance score."""
        if not self.endpoints_tested:
            return 0.0
        total = sum(e.overall_score for e in self.endpoints_tested)
        return total / len(self.endpoints_tested)

    def common_failures(self) -> dict:
        """Find common failure patterns across endpoints."""
        failures = {}
        for result in self.endpoints_tested:
            for test in result.test_results:
                if test.status == "FAIL":
                    key = f"{test.category}:{test.test}"
                    failures[key] = failures.get(key, 0) + 1
        # Sort by frequency
        return dict(sorted(failures.items(), key=lambda x: x[1], reverse=True))

    def unique_failures(self) -> dict:
        """Find failures unique to each endpoint."""
        unique = {}
        all_failures = self.common_failures()

        for failure, count in all_failures.items():
            if count == 1:  # Only appears in one endpoint
                unique[failure] = count

        return unique

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "batch_timestamp": self.batch_timestamp,
            "total_duration_seconds": round(self.total_duration, 2),
            "endpoints_tested": len(self.endpoints_tested),
            "average_score": round(self.average_score(), 2),
            "best_performer": self.best_performer().endpoint.name if self.best_performer() else None,
            "worst_performer": self.worst_performer().endpoint.name if self.worst_performer() else None,
            "results": [r.to_dict() for r in self.endpoints_tested],
            "common_failures": self.common_failures(),
            "unique_failures": self.unique_failures(),
        }


class BatchTestRunner:
    """Runs assurance tests against multiple external endpoints."""

    def __init__(self, endpoints: List[ServerEndpoint]):
        """
        Initialize batch runner.

        Args:
            endpoints: List of ServerEndpoint configurations
        """
        self.endpoints = endpoints
        self.results = BatchTestResults()

    def test_endpoint(self, endpoint: ServerEndpoint) -> EndpointTestResult:
        """
        Test a single endpoint.

        Args:
            endpoint: ServerEndpoint to test

        Returns:
            EndpointTestResult with test outcomes
        """
        result = EndpointTestResult(
            endpoint=endpoint,
            test_timestamp=datetime.now().isoformat(),
        )

        try:
            # Create external client
            client = ExternalMCPClient(endpoint)
            protocol_version = endpoint.metadata.get(
                "protocol_version",
                "2025-11-25",
            )

            # Run core tests
            test_functions = [
                run_initialize_test,
                run_tools_list_test,
                run_resources_list_test,
                run_prompts_list_test,
                run_tool_execution_test,
            ]

            for test_func in test_functions:
                try:
                    test_result = test_func(client.client, protocol_version)
                    result.test_results.append(test_result)
                except Exception as e:
                    result.error_message = str(e)
                    break
            client.close()

            # Calculate scores
            if result.test_results:
                passed = result.passed_count()
                total = result.total_count()
                result.overall_score = (passed / total * 100) if total > 0 else 0

                # Categorize scores
                protocol_tests = [
                    r for r in result.test_results
                    if r.category == "Protocol Conformance"
                ]
                functional_tests = [
                    r for r in result.test_results
                    if r.category == "Functional Correctness"
                ]
                security_tests = [
                    r for r in result.test_results
                    if r.category in (
                        "Basic Security Validation",
                        "Advanced Negative Validation",
                    )
                ]

                if protocol_tests:
                    result.protocol_score = (sum(1 for t in protocol_tests if t.status == "PASS") / len(protocol_tests)) * 100
                if functional_tests:
                    result.functional_score = (sum(1 for t in functional_tests if t.status == "PASS") / len(functional_tests)) * 100
                if security_tests:
                    result.security_score = (sum(1 for t in security_tests if t.status == "PASS") / len(security_tests)) * 100

            # Collect metrics
            result.metrics = client.get_metrics().to_dict()

        except Exception as e:
            result.error_message = str(e)

        return result

    def run_batch(self) -> BatchTestResults:
        """
        Run tests against all endpoints.

        Returns:
            BatchTestResults with all endpoint results
        """
        self.results.batch_timestamp = datetime.now().isoformat()
        start_time = datetime.now()

        print(f"\nBatch Testing {len(self.endpoints)} Endpoints")
        print("=" * 80)

        for i, endpoint in enumerate(self.endpoints, 1):
            print(f"\n[{i}/{len(self.endpoints)}] Testing: {endpoint}")

            result = self.test_endpoint(endpoint)
            self.results.endpoints_tested.append(result)

            if result.error_message:
                print(f"  ⚠ Error: {result.error_message}")
            else:
                print(f"  ✓ Score: {result.overall_score:.1f}%")
                print(f"    Tests: {result.passed_count()}/{result.total_count()} passed")

        self.results.total_duration = (datetime.now() - start_time).total_seconds()

        print("\n" + "=" * 80)
        print("Batch Testing Complete")
        print(f"Average Score: {self.results.average_score():.1f}%")
        print(f"Duration: {self.results.total_duration:.1f}s")

        return self.results

    def save_results_json(self, output_file: Path) -> None:
        """
        Save batch results as JSON.

        Args:
            output_file: Output file path
        """
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.results.to_dict(), f, indent=2)
        print(f"Saved batch results: {output_file}")

    def save_individual_results(self, output_dir: Path) -> None:
        """
        Save individual endpoint results.

        Args:
            output_dir: Output directory
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        for result in self.results.endpoints_tested:
            filename = f"{result.endpoint.name.lower().replace(' ', '_')}_result.json"
            output_file = output_dir / filename
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(result.to_dict(), f, indent=2)
        print(f"Saved {len(self.results.endpoints_tested)} individual results to {output_dir}")
