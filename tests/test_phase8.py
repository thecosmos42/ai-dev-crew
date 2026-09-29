from pathlib import Path

from sdlc_agents.eval.harness import run_e2e
from sdlc_agents.eval.scoring import score_design, score_dev, score_pipeline, score_review
from sdlc_agents.metrics.db import MetricsDB
from sdlc_agents.schemas import DesignDoc, DevResult, ReviewResult, TestSummary as ReviewTestSummary


def test_scoring_functions() -> None:
    design = DesignDoc(summary="x", affected_modules=["loan_calc/rates.py"], approach="x", edge_cases=[], test_scenarios=[], confidence=0.9)
    assert score_design(design, {"design": "clean", "expected_modules": ["loan_calc/rates.py"]})["correct"]
    assert score_dev(DevResult(status="blocked", blocked_reason="conflict"), {"dev": "blocked"})["correct"]
    review = ReviewResult(risk_level="low", violations=[], missing_coverage=[], test_summary=ReviewTestSummary(passed=1, failed=0, total=1), approval_decision="approve", rationale="ok")
    assert score_review(review, {"review": "approve"})["correct"]
    assert score_pipeline("approved", {"pipeline": ["approved"]})


def test_metrics_rows_can_store_correctness(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "eval.db")
    db.insert_run(run_id="run", batch_id="batch", ticket_id="T1", mode="e2e", repeat_index=0)
    db.update_run("run", pipeline_outcome="approved", pipeline_correct=1)
    with db.connect() as connection:
        row = connection.execute("SELECT pipeline_correct FROM runs WHERE run_id = 'run'").fetchone()
    assert row["pipeline_correct"] == 1


def test_offline_e2e_records_measured_latency_and_pricing(tmp_path: Path) -> None:
    from sdlc_agents.config import Settings

    result = run_e2e(
        settings=Settings(
            sdlc_db_path=tmp_path / "eval.db",
            pricing_path=Path("config/pricing.yaml"),
        )
    )
    assert result["correct"] > 0
    database = MetricsDB(tmp_path / "eval.db")
    with database.connect() as connection:
        latency = connection.execute("SELECT MIN(latency_ms) FROM agent_runs").fetchone()[0]
        pricing_rows = connection.execute("SELECT COUNT(*) FROM pricing").fetchone()[0]
    assert latency > 0
    assert pricing_rows == 1