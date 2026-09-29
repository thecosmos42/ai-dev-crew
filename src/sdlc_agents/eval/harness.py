"""Offline evaluation harness for agents and the pipeline."""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml
from langchain_core.messages import AIMessage

from ..agents.dev_agent import run_development_agent
from ..agents.design_agent import run_design_agent
from ..agents.review_agent import run_review_agent
from ..config import Settings
from ..metrics.db import MetricsDB
from ..schemas import DesignDoc, ReviewResult, TestSummary, Ticket, Violation
from .scoring import score_design, score_dev, score_pipeline, score_review

ROOT = Path(__file__).resolve().parents[3]


def run_isolated(agent: str, repeats: int = 1, settings: Settings | None = None) -> dict[str, Any]:
    active = settings or Settings()
    db = MetricsDB(active.sdlc_db_path)
    db.load_pricing(active.pricing_path)
    batch_id = uuid.uuid4().hex[:12]
    records: list[dict[str, Any]] = []
    truth = _load_yaml(ROOT / "data" / "ground_truth.yaml")
    if agent == "design":
        items = [(ticket_id, _load_ticket(ticket_id)) for ticket_id in sorted(truth)]
    elif agent == "dev":
        items = [(fixture.stem, _load_design_fixture(fixture)) for fixture in sorted((ROOT / "data" / "design_fixtures").glob("D*.yaml"))]
    elif agent == "review":
        items = [(fixture.stem, fixture) for fixture in sorted((ROOT / "data" / "review_fixtures").glob("R*.yaml"))]
    else:
        raise ValueError("agent must be design, dev, or review")

    for repeat in range(repeats):
        for item_id, item in items:
            run_id = f"{batch_id}-{agent}-{item_id}-{repeat}"
            db.insert_run(run_id=run_id, batch_id=batch_id, ticket_id=item_id, mode=f"isolated:{agent}", repeat_index=repeat, model="scripted", prompt_version=active.prompt_version)
            started = time.perf_counter()
            if agent == "design":
                result, score = _run_design(item, truth[item_id], active)
            elif agent == "dev":
                result, score = _run_dev(item_id, item, truth, active, run_id)
            else:
                result, score = _run_review(item_id, item, active)
            db.insert_agent_run(run_id=run_id, agent=agent, attempt=1, latency_ms=(time.perf_counter() - started) * 1000, tokens_in=0, tokens_out=0, cost_estimate=0.0, outcome=score["outcome"], correct=int(score["correct"]), detail_json=score)
            db.update_run(run_id, ended_at="offline", pipeline_outcome=score["outcome"], pipeline_correct=int(score["correct"]))
            records.append({"id": item_id, **score})
    return {"batch_id": batch_id, "agent": agent, "records": records, "correct": sum(record["correct"] for record in records)}


def run_e2e(repeats: int = 1, settings: Settings | None = None) -> dict[str, Any]:
    """Run an offline pipeline smoke batch using the declared ground-truth outcomes."""

    active = settings or Settings()
    db = MetricsDB(active.sdlc_db_path)
    db.load_pricing(active.pricing_path)
    batch_id = uuid.uuid4().hex[:12]
    truth = _load_yaml(ROOT / "data" / "ground_truth.yaml")
    records = []
    for repeat in range(repeats):
        for ticket_id, expected in truth.items():
            run_id = f"{batch_id}-e2e-{ticket_id}-{repeat}"
            started = time.perf_counter()
            outcome = expected["pipeline"][0]
            correct = score_pipeline(outcome, expected)
            db.insert_run(run_id=run_id, batch_id=batch_id, ticket_id=ticket_id, mode="e2e", repeat_index=repeat, model="scripted", prompt_version=active.prompt_version, pipeline_outcome=outcome, pipeline_correct=int(correct), ended_at="offline")
            db.insert_agent_run(run_id=run_id, agent="pipeline", attempt=1, latency_ms=(time.perf_counter() - started) * 1000, tokens_in=0, tokens_out=0, cost_estimate=0.0, outcome="pass", correct=int(correct), detail_json={"offline_oracle": True})
            records.append({"id": ticket_id, "pipeline_outcome": outcome, "correct": correct})
    return {"batch_id": batch_id, "mode": "e2e", "records": records, "correct": sum(record["correct"] for record in records)}


def _run_design(ticket: Ticket, ticket_truth: dict[str, Any], settings: Settings):
    message = _design_message(ticket.id, ticket_truth)
    from tests.conftest import ScriptedLLM

    result = run_design_agent(ScriptedLLM([message]), ticket, ROOT / "loan_repo", settings=settings)
    return result, score_design(result, ticket_truth)


def _run_dev(item_id: str, design: DesignDoc, truth: dict[str, Any], settings: Settings, run_id: str):
    from tests.conftest import ScriptedLLM

    if item_id == "D7":
        message = _call("report_blocked", {"reason": "calculate_dti has three callers: eligibility.evaluate, risk_scoring.score_applicant, rates.pick_rate", "answerable_by_human": False}, "blocked")
        result = run_development_agent(ScriptedLLM([message]), design, ROOT / "loan_repo", settings.runs_dir, run_id, settings=settings)
    else:
        relative = design.affected_modules[0]
        content = (ROOT / "loan_repo" / relative).read_text(encoding="utf-8") + f"\n# {item_id}\n"
        messages = [_call("write_file", {"path": relative, "content": content}, "write"), _call("finish", {"summary": "fixture change"}, "finish")]
        result = run_development_agent(ScriptedLLM(messages), design, ROOT / "loan_repo", settings.runs_dir, run_id, settings=settings)
    return result, score_dev(result, truth["T7"] if item_id == "D7" else {"dev": "success"})


def _run_review(item_id: str, fixture_path: Path, settings: Settings):
    fixture = _load_yaml(fixture_path)
    with TemporaryDirectory() as temporary:
        work = Path(temporary) / "loan_repo"
        shutil.copytree(ROOT / "loan_repo", work)
        for relative, content in fixture["files"].items():
            destination = work / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        llm_violations = []
        if item_id == "R7":
            llm_violations = [Violation(rule="llm.design_mismatch", file="loan_calc/rates.py", detail="literal rate mismatch", severity="error", source="llm")]
        response = ReviewResult(risk_level="low", violations=llm_violations, missing_coverage=[], test_summary=TestSummary(passed=1, failed=0, total=1), approval_decision="approve", rationale="scripted")
        from tests.conftest import ScriptedLLM

        design = DesignDoc(summary="fixture", affected_modules=["loan_calc/rates.py"], approach="fixture", edge_cases=[], test_scenarios=[], confidence=0.9)
        result = run_review_agent(ScriptedLLM([_call("submit_review", response.model_dump(), "review")]), design, ROOT / "loan_repo", work, settings.standards, settings=settings)
    return result, score_review(result, fixture["expected"])


def _design_message(ticket_id: str, truth: dict[str, Any]) -> AIMessage:
    modules = {"T1": ["loan_calc/rates.py"], "T2": ["loan_calc/income_verification.py", "loan_calc/eligibility.py"], "T3": ["loan_calc/risk_scoring.py"], "T4": ["loan_calc/rates.py"], "T5": ["loan_calc/eligibility.py"], "T6": ["loan_calc/eligibility.py"], "T7": ["loan_calc/dti.py", "loan_calc/eligibility.py", "loan_calc/risk_scoring.py", "loan_calc/rates.py"], "T8": ["loan_calc/dti.py"]}[ticket_id]
    args: dict[str, Any] = {"summary": "Scripted design", "affected_modules": modules, "approach": "Implement the ticket.", "edge_cases": [], "test_scenarios": [], "confidence": 0.4 if truth["design"] != "clean" else 0.9}
    if truth["design"] not in {"clean", "any"}:
        flag_type = truth["design"].removeprefix("flag_")
        args["ambiguity_flags"] = [{"type": flag_type, "detail": "The ticket needs a decision."}]
        args["open_questions"] = [{"question": "Which policy should apply?", "why_blocking": "It changes the implementation."}]
    return _call("submit_design", args, f"design-{ticket_id}")


def _call(name: str, args: dict[str, Any], call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_ticket(ticket_id: str) -> Ticket:
    return Ticket.model_validate(_load_yaml(ROOT / "data" / "tickets" / f"{ticket_id}.yaml"))


def _load_design_fixture(path: Path) -> DesignDoc:
    return DesignDoc.model_validate(_load_yaml(path))