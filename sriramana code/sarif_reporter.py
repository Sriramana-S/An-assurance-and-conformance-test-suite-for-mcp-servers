#!/usr/bin/env python
"""
SARIF 2.1.0 reporter for the MCP Assurance Suite.

SARIF (Static Analysis Results Interchange Format) is the format GitHub
Advanced Security consumes to render code-scanning alerts. Exporting the
suite's conformance findings as SARIF lets them surface as inline GitHub
security alerts.

The tool component (tool.driver.rules) documents all 34 assurance cases as
rules (MCP001-MCP034). Per SARIF convention only *findings* are emitted as
results: FAIL and WARN. PASS and SKIP produce no result (a clean target yields
an empty results array).

CLI:
  python sarif_reporter.py --input  reports/ci/compliance_report.json \\
                           --output reports/ci/compliance_report.sarif \\
                           --target "server-everything"
"""
import argparse
import json
import re
import sys
from pathlib import Path

from core.suite import DEFAULT_CASES
from core.unified_reporter import REMEDIATION_HINTS, GENERIC_REMEDIATION

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
TOOL_NAME = "MCP Assurance Suite"
TOOL_VERSION = "1.0.0"
INFORMATION_URI = "https://github.com/mcp-assurance-suite/mcp-assurance-suite"
SPEC_HELP_URI = "https://modelcontextprotocol.io/specification/2025-11-25"


def _field(item, name, default=None):
    """Read a field from an AssuranceResult object OR a result dict."""
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _camel_case(name: str) -> str:
    """'Non-Object JSON Rejection' -> 'NonObjectJSONRejection' (preserve the
    casing of already-capitalised tokens like JSON / JSON-RPC)."""
    tokens = [t for t in re.split(r"[^A-Za-z0-9]+", name) if t]
    return "".join(t[:1].upper() + t[1:] for t in tokens) or "Case"


def _rule_level(conformance_level: str) -> str:
    """SARIF defaultConfiguration level for a rule: MUST -> error, else warning."""
    return "error" if conformance_level == "MUST" else "warning"


def _result_level(status: str, conformance_level: str) -> str:
    """error = MUST FAIL, warning = WARN or SHOULD FAIL, note = PASS."""
    if status == "FAIL":
        return "error" if conformance_level == "MUST" else "warning"
    if status == "WARN":
        return "warning"
    return "note"


def _remediation(test_name: str) -> str:
    entry = REMEDIATION_HINTS.get(test_name)
    return entry[0] if entry else GENERIC_REMEDIATION


class SARIFReporter:
    """Builds SARIF 2.1.0 logs from assurance results."""

    def __init__(self):
        # Stable rule id / index per assurance case, in DEFAULT_CASES order.
        self._rule_id = {}
        self._rule_index = {}
        for i, case in enumerate(DEFAULT_CASES):
            self._rule_id[case.name] = f"MCP{i + 1:03d}"
            self._rule_index[case.name] = i

    def _build_rules(self) -> list:
        rules = []
        for case in DEFAULT_CASES:
            level = case.conformance_level
            rules.append({
                "id": self._rule_id[case.name],
                "name": _camel_case(case.name),
                "shortDescription": {"text": case.name},
                "fullDescription": {
                    "text": f"{case.category} / {level} conformance check: "
                            f"{case.name}. {case.spec_clause}".strip()
                },
                "helpUri": SPEC_HELP_URI,
                "help": {"text": case.spec_clause or "MCP conformance case."},
                "properties": {
                    "tags": ["mcp-conformance", level, case.category],
                    "precision": "high",
                    "specClause": case.spec_clause,
                },
                "defaultConfiguration": {"level": _rule_level(level)},
            })
        return rules

    def _build_results(self, results, target_name: str) -> list:
        out = []
        for item in results:
            status = _field(item, "status", "")
            # SARIF convention: only emit findings. PASS and SKIP are not alerts.
            if status not in ("FAIL", "WARN"):
                continue

            test = _field(item, "test", "Unknown")
            level = _field(item, "conformance_level", "MUST")
            message = _field(item, "message", "") or ""
            remediation = _remediation(test)
            text = f"{message} Remediation: {remediation}".strip()

            rule_id = self._rule_id.get(test, "MCP000")
            result = {
                "ruleId": rule_id,
                "level": _result_level(status, level),
                "message": {"text": text},
                "locations": [{
                    "physicalLocation": {
                        "artifactLocation": {"uri": f"server://{target_name}"},
                        "region": {"startLine": 1},
                    }
                }],
                "properties": {
                    "tags": ["mcp-conformance", level],
                    "status": status,
                    "category": _field(item, "category", ""),
                    "conformanceLevel": level,
                    "specClause": _field(item, "spec_clause", ""),
                },
            }
            if test in self._rule_index:
                result["ruleIndex"] = self._rule_index[test]
            out.append(result)
        return out

    def build_log(self, results, target_name: str) -> dict:
        return {
            "version": SARIF_VERSION,
            "$schema": SARIF_SCHEMA,
            "runs": [{
                "tool": {
                    "driver": {
                        "name": TOOL_NAME,
                        "version": TOOL_VERSION,
                        "informationUri": INFORMATION_URI,
                        "rules": self._build_rules(),
                    }
                },
                "results": self._build_results(results, target_name),
            }],
        }

    def export(self, results, target_name: str, output_path: str) -> dict:
        """Write a SARIF 2.1.0 log for `results` and return the log dict."""
        log = self.build_log(results, target_name)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(log, indent=2), encoding="utf-8")
        return log


def main():
    parser = argparse.ArgumentParser(
        description="Convert an MCP compliance JSON report to SARIF 2.1.0.")
    parser.add_argument("--input", required=True,
                        help="Path to a compliance_report.json file.")
    parser.add_argument("--output", required=True,
                        help="Path to write the .sarif file.")
    parser.add_argument("--target", default="mcp-target",
                        help="Target name for result locations "
                             "(e.g. server-everything).")
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    results = data.get("results", [])
    log = SARIFReporter().export(results, args.target, args.output)
    n_results = len(log["runs"][0]["results"])
    n_rules = len(log["runs"][0]["tool"]["driver"]["rules"])
    print(f"SARIF written: {args.output}")
    print(f"  rules: {n_rules}  |  results (findings): {n_results}  "
          f"|  target: {args.target}")


if __name__ == "__main__":
    main()
