from dataclasses import dataclass, field
from typing import Any


@dataclass
class ClientResponse:
    status_code: int | None
    body: Any = None
    text: str = ""
    transport_error: str | None = None
    response_time_ms: float | None = None
    transport_type: str | None = None

    @property
    def has_transport_error(self) -> bool:
        return self.transport_error is not None


@dataclass
class TransportMetrics:
    transport_type: str
    request_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    response_time_total_ms: float = 0.0
    response_time_min_ms: float | None = None
    response_time_max_ms: float | None = None

    def record(self, response: ClientResponse, elapsed_ms: float) -> None:
        self.request_count += 1
        self.response_time_total_ms += elapsed_ms

        if self.response_time_min_ms is None:
            self.response_time_min_ms = elapsed_ms
        else:
            self.response_time_min_ms = min(self.response_time_min_ms, elapsed_ms)

        if self.response_time_max_ms is None:
            self.response_time_max_ms = elapsed_ms
        else:
            self.response_time_max_ms = max(self.response_time_max_ms, elapsed_ms)

        if response.has_transport_error:
            self.failure_count += 1
        else:
            self.success_count += 1

    @property
    def average_response_time_ms(self) -> float:
        if self.request_count == 0:
            return 0.0
        return self.response_time_total_ms / self.request_count

    @property
    def failure_rate(self) -> float:
        if self.request_count == 0:
            return 0.0
        return (self.failure_count / self.request_count) * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "transport_type": self.transport_type,
            "request_count": self.request_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "average_response_time_ms": round(
                self.average_response_time_ms,
                2,
            ),
            "min_response_time_ms": round(self.response_time_min_ms or 0.0, 2),
            "max_response_time_ms": round(self.response_time_max_ms or 0.0, 2),
            "failure_rate_percent": round(self.failure_rate, 2),
        }


@dataclass
class ValidationResult:
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class AssuranceResult:
    test: str
    category: str
    status: str
    message: str
    severity: str = "medium"
    evidence: dict[str, Any] = field(default_factory=dict)
    # Spec-level conformance tagging. conformance_level is one of
    # "MUST", "SHOULD", "MAY"; spec_clause is the normative reference.
    conformance_level: str = "MUST"
    spec_clause: str = ""

    @classmethod
    def pass_result(
        cls,
        test: str,
        category: str,
        message: str,
        evidence: dict[str, Any] | None = None,
        severity: str = "medium",
        conformance_level: str = "MUST",
        spec_clause: str = "",
    ) -> "AssuranceResult":
        return cls(
            test,
            category,
            "PASS",
            message,
            severity,
            evidence or {},
            conformance_level,
            spec_clause,
        )

    @classmethod
    def fail_result(
        cls,
        test: str,
        category: str,
        message: str,
        evidence: dict[str, Any] | None = None,
        severity: str = "medium",
        conformance_level: str = "MUST",
        spec_clause: str = "",
    ) -> "AssuranceResult":
        return cls(
            test,
            category,
            "FAIL",
            message,
            severity,
            evidence or {},
            conformance_level,
            spec_clause,
        )

    @classmethod
    def warn_result(
        cls,
        test: str,
        category: str,
        message: str,
        evidence: dict[str, Any] | None = None,
        severity: str = "medium",
        conformance_level: str = "SHOULD",
        spec_clause: str = "",
    ) -> "AssuranceResult":
        return cls(
            test,
            category,
            "WARN",
            message,
            severity,
            evidence or {},
            conformance_level,
            spec_clause,
        )

    @classmethod
    def skip_result(
        cls,
        test: str,
        category: str,
        message: str,
        evidence: dict[str, Any] | None = None,
        conformance_level: str = "MUST",
        spec_clause: str = "",
    ) -> "AssuranceResult":
        return cls(
            test,
            category,
            "SKIP",
            message,
            "low",
            evidence or {},
            conformance_level,
            spec_clause,
        )
