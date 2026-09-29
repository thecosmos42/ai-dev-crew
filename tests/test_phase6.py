from pathlib import Path

from langchain_core.messages import AIMessage

from sdlc_agents.agents.review_agent import apply_hard_gates, run_review_agent
from sdlc_agents.schemas import CoverageGap, DesignDoc, ReviewResult, TestSummary as ReviewTestSummary, Violation


def clean_result() -> ReviewResult:
    return ReviewResult(
        risk_level="low",
        violations=[],
        missing_coverage=[],
        test_summary=ReviewTestSummary(passed=3, failed=0, total=3),
        approval_decision="approve",
        rationale="Looks good.",
    )


def test_hard_gates_reject_failing_tests_and_raise_risk() -> None:
    result = apply_hard_gates(
        clean_result(),
        {"test_summary": {"passed": 2, "failed": 1, "total": 3}},
    )
    assert result.approval_decision == "reject"
    assert result.risk_level == "high"
    assert "tests.failing" in result.gate_overrides


def test_hard_gates_merge_sensitive_coverage_gap() -> None:
    gap = CoverageGap(file="loan_calc/risk_scoring.py", required=90, actual=80, sensitive=True)
    result = apply_hard_gates(clean_result(), {"coverage_gaps": [gap.model_dump()]})
    assert result.approval_decision == "reject"
    assert result.risk_level == "high"
    assert result.missing_coverage == [gap]


def test_hard_gates_never_lower_llm_risk() -> None:
    result = clean_result().model_copy(update={"risk_level": "high"})
    gated = apply_hard_gates(result, {})
    assert gated.risk_level == "high"
    assert gated.approval_decision == "approve"


def test_hard_gates_merge_error_violation() -> None:
    violation = Violation(rule="naming.function_snake_case", file="dti.py", detail="camelCase", severity="error", source="code")
    result = apply_hard_gates(clean_result(), {"violations": [violation.model_dump()]})
    assert result.approval_decision == "reject"
    assert result.risk_level == "medium"
    assert result.violations == [violation]


def test_review_agent_catches_llm_design_mismatch(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    work = tmp_path / "work"
    baseline.mkdir()
    work.mkdir()
    (baseline / "module.py").write_text("RATE = 0.0525\n", encoding="utf-8")
    (work / "module.py").write_text("RATE = 0.0552\n", encoding="utf-8")
    design = DesignDoc(
        summary="Use the exact rate",
        affected_modules=["module.py"],
        approach="Set RATE to 0.0525.",
        edge_cases=[],
        test_scenarios=[],
        confidence=0.9,
    )
    llm_result = clean_result().model_copy(
        update={
            "approval_decision": "reject",
            "violations": [
                Violation(
                    rule="llm.design_mismatch",
                    file="module.py",
                    detail="0.0552 does not match the designed 0.0525 value",
                    severity="error",
                    source="llm",
                )
            ],
        }
    )
    message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "submit_review",
                "args": llm_result.model_dump(),
                "id": "review-1",
                "type": "tool_call",
            }
        ],
    )
    from tests.conftest import ScriptedLLM

    result = run_review_agent(ScriptedLLM([message]), design, baseline, work, {"coverage": {"default_min": 0}})
    assert result is not None
    assert result.approval_decision == "reject"
    assert any(violation.rule == "llm.design_mismatch" for violation in result.violations)