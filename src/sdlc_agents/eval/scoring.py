"""Pure scoring functions for isolated and pipeline evaluations."""

from __future__ import annotations

from typing import Any

from ..schemas import DesignDoc, DevResult, ReviewResult


def score_design(design: DesignDoc | None, truth: dict[str, Any]) -> dict[str, Any]:
    expected = truth.get("design", "clean")
    if design is None:
        return {"correct": False, "outcome": "fail", "module_recall": 0.0}
    if expected in {"clean", "any"}:
        correct = not design.ambiguity_flags and not design.open_questions
    else:
        expected_type = expected.removeprefix("flag_")
        correct = any(flag.type == expected_type for flag in design.ambiguity_flags) and bool(design.open_questions)
    expected_modules = set(truth.get("expected_modules", []))
    actual_modules = set(design.affected_modules)
    recall = len(expected_modules & actual_modules) / len(expected_modules) if expected_modules else 1.0
    return {"correct": correct, "outcome": "flagged" if design.open_questions else "pass", "module_recall": recall}


def score_dev(result: DevResult | None, truth: dict[str, Any]) -> dict[str, Any]:
    expected = truth.get("dev", "success")
    if result is None:
        return {"correct": False, "outcome": "fail"}
    if expected == "blocked":
        correct = result.status == "blocked" and not result.diff and bool(result.blocked_reason)
    else:
        correct = result.status == "success" and bool(result.diff)
    return {"correct": correct, "outcome": "blocked" if result.status == "blocked" else "pass"}


def score_review(result: ReviewResult | None, truth: dict[str, Any]) -> dict[str, Any]:
    if result is None:
        return {"correct": False, "outcome": "fail"}
    expected_decision = truth.get("review", truth.get("decision"))
    expected_rules = set(truth.get("review_rules", truth.get("rules", [])))
    actual_rules = {violation.rule for violation in result.violations}
    correct = result.approval_decision == expected_decision and expected_rules <= actual_rules
    if expected_decision == "approve":
        correct = correct and not any(violation.severity == "error" for violation in result.violations)
    return {"correct": correct, "outcome": "flagged" if result.approval_decision == "reject" else "pass", "rules": sorted(actual_rules)}


def score_pipeline(outcome: str | None, truth: dict[str, Any]) -> bool:
    return outcome in truth.get("pipeline", [])