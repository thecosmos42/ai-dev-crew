"""Review Agent and deterministic hard gates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..config import Settings
from ..llm import LLMClient
from ..metrics.tracker import UsageTracker, get_current_tracker
from ..schemas import CoverageGap, DesignDoc, ReviewResult, TestSummary, Violation
from ..tools.checks import check_coverage, check_naming, check_test_tampering, check_untested_public_functions
from ..tools.diffing import make_diff
from ..tools.test_runner import TestRunResult, run_tests
from ..tools.repo_tools import RepoTools
from .base import run_tool_loop

REVIEW_SYSTEM = """You are the Review Agent. Review the design, code-generated diff, and authoritative facts.
Compare exact values and behavior against the design. Add your own violations with source=llm and rule names starting llm.
Approve only when the diff matches the design and there are no error-level violations.
Finish by calling submit_review exactly once. Never contradict the FACTS block."""


def apply_hard_gates(result: ReviewResult, facts: dict[str, Any]) -> ReviewResult:
    """Enforce deterministic review gates while preserving LLM findings."""

    violations = _models(facts.get("violations", []), Violation)
    gaps = _models(facts.get("coverage_gaps", facts.get("missing_coverage", [])), CoverageGap)
    merged_violations = _merge_models(result.violations, violations)
    merged_gaps = _merge_models(result.missing_coverage, gaps)
    summary = _model(facts.get("test_summary"), TestSummary) or result.test_summary

    floor = "low"
    overrides: list[str] = []
    if summary.failed > 0:
        floor = "high"
        overrides.append("tests.failing")
    elif merged_gaps:
        floor = "high" if any(gap.sensitive for gap in merged_gaps) else "medium"
        overrides.append("coverage.below_threshold")
    elif any(violation.severity == "error" for violation in merged_violations):
        floor = "medium"
        overrides.append("error_severity_violation")

    risk = _max_risk(result.risk_level, floor)
    decision = result.approval_decision
    if floor != "low" and decision != "reject":
        decision = "reject"
        overrides.append("approval_gate")
    existing_overrides = list(result.gate_overrides)
    for override in overrides:
        if override not in existing_overrides:
            existing_overrides.append(override)
    return result.model_copy(
        update={
            "violations": merged_violations,
            "missing_coverage": merged_gaps,
            "test_summary": summary,
            "risk_level": risk,
            "approval_decision": decision,
            "gate_overrides": existing_overrides,
        }
    )


def run_review_agent(
    llm: LLMClient,
    design: DesignDoc,
    baseline_path: str | Path,
    work_path: str | Path,
    standards: dict[str, Any],
    settings: Settings | None = None,
    tracker: UsageTracker | None = None,
) -> ReviewResult | None:
    active_settings = settings or Settings()
    active_tracker = tracker or get_current_tracker() or UsageTracker()
    baseline = Path(baseline_path)
    work = Path(work_path)
    test_result = run_tests(work)
    active_tracker.tool_calls += 1
    diff, changed_files = make_diff(baseline, work)
    changed_py_files = [
        (baseline / relative if (baseline / relative).exists() else None, work / relative)
        for relative in changed_files
        if relative.endswith(".py") and (work / relative).exists()
    ]
    code_violations = check_naming(changed_py_files, standards)
    code_violations.extend(check_test_tampering(baseline, work))
    code_violations.extend(check_untested_public_functions(baseline, work))
    if test_result.summary.failed:
        code_violations.append(
            Violation(
                rule="tests.failing",
                file=None,
                detail=f"{test_result.summary.failed} test(s) failed",
                severity="error",
                source="code",
            )
        )
    gaps, coverage_violations = check_coverage(test_result.coverage, standards)
    code_violations.extend(coverage_violations)
    facts = {
        "test_summary": test_result.summary.model_dump(),
        "coverage": test_result.coverage,
        "coverage_gaps": [gap.model_dump() for gap in gaps],
        "violations": [violation.model_dump() for violation in code_violations],
        "diff": diff,
        "design": design.model_dump(),
    }
    user = json.dumps(facts, separators=(",", ":"))
    repository = RepoTools(work)
    response = run_tool_loop(
        llm=llm,
        system=REVIEW_SYSTEM,
        user=user,
        tools=repository.as_tools()[1:2],
        terminal_models={"submit_review": ReviewResult},
        max_iters=active_settings.max_tool_iterations,
        tracker=active_tracker,
        max_schema_retries=active_settings.max_schema_retries,
    )
    if not isinstance(response, ReviewResult):
        return None
    return apply_hard_gates(response, facts)


def _model(value: Any, model_type: type[BaseModel]) -> BaseModel | None:
    if value is None:
        return None
    if isinstance(value, model_type):
        return value
    return model_type.model_validate(value)


def _models(values: list[Any], model_type: type[BaseModel]) -> list[BaseModel]:
    return [_model(value, model_type) for value in values if _model(value, model_type) is not None]


def _merge_models(existing: list[BaseModel], additions: list[BaseModel]) -> list[Any]:
    merged: list[BaseModel] = list(existing)
    seen = {json.dumps(model.model_dump(), sort_keys=True) for model in merged}
    for model in additions:
        marker = json.dumps(model.model_dump(), sort_keys=True)
        if marker not in seen:
            merged.append(model)
            seen.add(marker)
    return merged


def _max_risk(current: str, floor: str) -> str:
    levels = {"low": 0, "medium": 1, "high": 2}
    return current if levels[current] >= levels[floor] else floor