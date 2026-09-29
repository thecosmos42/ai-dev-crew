"""Small Phase 7 CLI entry points."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from .config import Settings
from .graph import build_graph
from .llm import get_llm
from .schemas import Ticket
from .state import PipelineState
from .eval.harness import run_e2e, run_isolated
from .metrics.db import MetricsDB

app = typer.Typer()
eval_app = typer.Typer()
app.add_typer(eval_app, name="eval")
ROOT = Path(__file__).resolve().parents[2]


def load_ticket(ticket_id: str) -> Ticket:
    import yaml

    path = ROOT / "data" / "tickets" / f"{ticket_id}.yaml"
    return Ticket.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@app.command()
def design(ticket_id: str) -> None:
    settings = Settings()
    from .agents.design_agent import run_design_agent

    result = run_design_agent(get_llm(settings), load_ticket(ticket_id), ROOT / "loan_repo", settings=settings)
    typer.echo(result.model_dump_json(indent=2) if result else "design failed")


@app.command()
def run(ticket_id: str, interactive: bool = False) -> None:
    settings = Settings()
    if interactive:
        settings = settings.model_copy(update={"max_tool_iterations": max(settings.max_tool_iterations, 8)})
    ticket = load_ticket(ticket_id)
    initial = PipelineState(
        run_id=f"cli-{ticket_id}",
        ticket=ticket,
        repo_path=ROOT / "loan_repo",
        baseline_path=ROOT / "loan_repo",
        max_dev_retries=1,
    )
    graph = build_graph(get_llm(settings), settings)
    config = {"configurable": {"thread_id": initial.run_id}}
    result = graph.invoke(initial, config)
    while "__interrupt__" in result:
        value = result["__interrupt__"][0].value
        answer = typer.prompt(json.dumps(value)) if interactive else "I don't know."
        from langgraph.types import Command

        result = graph.invoke(Command(resume=answer), config)
    typer.echo(json.dumps(result, default=str, indent=2))


@eval_app.command("isolated")
def eval_isolated(agent: str = typer.Option(..., "--agent"), repeats: int = 1) -> None:
    result = run_isolated(agent, repeats)
    typer.echo(json.dumps(result, default=str, indent=2))


@eval_app.command("e2e")
def eval_e2e(repeats: int = 1) -> None:
    result = run_e2e(repeats)
    typer.echo(json.dumps(result, default=str, indent=2))


@eval_app.command("report")
def eval_report() -> None:
    settings = Settings()
    database = MetricsDB(settings.sdlc_db_path)
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT mode, COUNT(*) AS runs, SUM(CASE WHEN pipeline_correct = 1 THEN 1 ELSE 0 END) AS correct "
            "FROM runs GROUP BY mode ORDER BY mode"
        ).fetchall()
    report = [{"mode": row["mode"], "runs": row["runs"], "correct": row["correct"] or 0} for row in rows]
    typer.echo(json.dumps({"modes": report}, indent=2))


if __name__ == "__main__":
    app()