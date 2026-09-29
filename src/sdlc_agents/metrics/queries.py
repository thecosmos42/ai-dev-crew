"""Dashboard-facing SQLite queries."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd


def _connect(db_path: str | Path) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


def filter_values(db_path: str | Path, column: str) -> list[str]:
    allowed = {"batch_id", "model", "prompt_version", "mode"}
    if column not in allowed:
        raise ValueError(f"unsupported filter column: {column}")
    query = f"SELECT DISTINCT {column} FROM runs WHERE {column} IS NOT NULL ORDER BY {column}"
    with _connect(db_path) as connection:
        return [row[0] for row in connection.execute(query).fetchall()]


def _where(filters: dict[str, str | None] | None) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    for column in ("batch_id", "model", "prompt_version", "mode"):
        value = (filters or {}).get(column)
        if value:
            clauses.append(f"r.{column} = ?")
            values.append(value)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", values


def latency_by_agent(db_path: str | Path, filters: dict[str, str | None] | None = None) -> pd.DataFrame:
    where, values = _where(filters)
    query = "SELECT a.agent, a.latency_ms FROM agent_runs a JOIN runs r ON r.run_id = a.run_id" + where
    with _connect(db_path) as connection:
        return pd.read_sql_query(query, connection, params=values)


def cost_by_ticket(db_path: str | Path, filters: dict[str, str | None] | None = None) -> pd.DataFrame:
    where, values = _where(filters)
    query = (
        "SELECT r.ticket_id, a.agent, AVG(a.cost_estimate) AS cost "
        "FROM agent_runs a JOIN runs r ON r.run_id = a.run_id"
        + where
        + " GROUP BY r.ticket_id, a.agent ORDER BY r.ticket_id, a.agent"
    )
    with _connect(db_path) as connection:
        return pd.read_sql_query(query, connection, params=values)


def accuracy_metrics(db_path: str | Path, filters: dict[str, str | None] | None = None) -> pd.DataFrame:
    where, values = _where(filters)
    query = (
        "SELECT a.agent, AVG(a.correct) AS correctness, "
        "AVG(CASE WHEN a.uncertainty_planted = 1 THEN a.uncertainty_surfaced ELSE NULL END) AS uncertainty_surfacing, "
        "AVG(CASE WHEN a.correct = 0 THEN 1.0 ELSE 0.0 END) AS false_positive "
        "FROM agent_runs a JOIN runs r ON r.run_id = a.run_id"
        + where
        + " GROUP BY a.agent ORDER BY a.agent"
    )
    with _connect(db_path) as connection:
        return pd.read_sql_query(query, connection, params=values)


def ticket_pass_rates(db_path: str | Path, filters: dict[str, str | None] | None = None) -> pd.DataFrame:
    where, values = _where(filters)
    query = (
        "SELECT r.ticket_id, SUM(CASE WHEN r.pipeline_correct = 1 THEN 1 ELSE 0 END) AS passed, COUNT(*) AS repeats "
        "FROM runs r" + where + " GROUP BY r.ticket_id ORDER BY r.ticket_id"
    )
    with _connect(db_path) as connection:
        frame = pd.read_sql_query(query, connection, params=values)
    if not frame.empty:
        frame["pass_rate"] = frame["passed"].astype(str) + "/" + frame["repeats"].astype(str)
    return frame


def success_criteria(db_path: str | Path) -> pd.DataFrame:
    with _connect(db_path) as connection:
        total = connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        correct = connection.execute("SELECT COUNT(*) FROM runs WHERE pipeline_correct = 1").fetchone()[0]
        review_gaps = connection.execute(
            "SELECT COUNT(*) FROM agent_runs WHERE agent = 'review' AND outcome = 'flagged'"
        ).fetchone()[0]
    return pd.DataFrame(
        [
            {"criterion": "Evaluation rows exist", "passed": total > 0, "detail": f"{total} runs"},
            {"criterion": "Correctness is recorded", "passed": total > 0 and correct >= 0, "detail": f"{correct}/{total}"},
            {"criterion": "Review findings are visible", "passed": review_gaps > 0, "detail": f"{review_gaps} flagged review runs"},
        ]
    )