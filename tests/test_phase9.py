from pathlib import Path

from sdlc_agents.metrics.db import MetricsDB
from sdlc_agents.metrics.queries import (
    accuracy_metrics,
    cost_by_ticket,
    latency_by_agent,
    success_criteria,
    ticket_pass_rates,
)


def test_dashboard_queries_return_aggregates(tmp_path: Path) -> None:
    database = MetricsDB(tmp_path / "metrics.db")
    database.insert_run(run_id="r1", batch_id="b1", ticket_id="T1", mode="e2e", model="m", prompt_version="v1", pipeline_correct=1)
    database.insert_agent_run(run_id="r1", agent="review", latency_ms=12, cost_estimate=0.3, correct=1, uncertainty_planted=0, uncertainty_surfaced=0)
    assert len(latency_by_agent(database.path)) == 1
    assert cost_by_ticket(database.path).iloc[0]["cost"] == 0.3
    assert accuracy_metrics(database.path).iloc[0]["correctness"] == 1
    assert ticket_pass_rates(database.path).iloc[0]["pass_rate"] == "1/1"
    assert not success_criteria(database.path).empty