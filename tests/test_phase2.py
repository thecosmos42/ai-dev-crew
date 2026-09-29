from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from sdlc_agents.llm import extract_usage
from sdlc_agents.metrics.db import MetricsDB
from sdlc_agents.metrics.tracker import UsageTracker, calculate_cost
from sdlc_agents.schemas import DesignDoc, Ticket


def test_ticket_rejects_blank_acceptance_criteria() -> None:
    with pytest.raises(ValidationError):
        Ticket(
            id="T",
            title="Title",
            description="Description",
            acceptance_criteria=["  "],
        )


def test_design_flags_require_open_questions() -> None:
    with pytest.raises(ValidationError):
        DesignDoc(
            summary="summary",
            affected_modules=[],
            approach="approach",
            edge_cases=[],
            test_scenarios=[],
            ambiguity_flags=[{"type": "vague", "detail": "missing value"}],
            confidence=0.4,
        )


def test_design_limits_questions_to_three() -> None:
    question = {"question": "What?", "why_blocking": "Because."}
    with pytest.raises(ValidationError):
        DesignDoc(
            summary="summary",
            affected_modules=[],
            approach="approach",
            edge_cases=[],
            test_scenarios=[],
            open_questions=[question, question, question, question],
            confidence=0.4,
        )


def test_extract_usage_and_cost() -> None:
    message = AIMessage(
        content="done",
        usage_metadata={"input_tokens": 1500, "output_tokens": 500, "total_tokens": 2000},
    )
    assert extract_usage(message) == (1500, 500)
    tracker = UsageTracker(tokens_in=1500, tokens_out=500)
    assert tracker.cost(2.0, 4.0) == pytest.approx(5.0)
    assert calculate_cost(1500, 500, 2.0, 4.0) == pytest.approx(5.0)


def test_metrics_db_creates_tables_and_records_rows(tmp_path: Path) -> None:
    database = MetricsDB(tmp_path / "metrics.db")
    database.insert_run(run_id="run-1", ticket_id="T1", pipeline_outcome="approved")
    database.insert_agent_run(
        run_id="run-1",
        agent="design",
        attempt=1,
        latency_ms=10,
        tokens_in=100,
        tokens_out=20,
        cost_estimate=0.2,
        outcome="pass",
    )
    database.update_correct("run-1", True)
    database.insert_hitl_event(run_id="run-1", agent="design", round=1, n_questions=1, answer_blank=0)
    with database.connect() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        run = connection.execute("SELECT pipeline_correct FROM runs WHERE run_id = 'run-1'").fetchone()
    assert {"runs", "agent_runs", "hitl_events", "pricing"} <= tables
    assert run["pipeline_correct"] == 1