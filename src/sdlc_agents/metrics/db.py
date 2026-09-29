"""SQLite persistence for pipeline and agent metrics."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import yaml

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
    run_id TEXT PRIMARY KEY, batch_id TEXT, ticket_id TEXT, mode TEXT,
    repeat_index INT, model TEXT, prompt_version TEXT, started_at TEXT,
    ended_at TEXT, pipeline_outcome TEXT, pipeline_correct INT
);
CREATE TABLE IF NOT EXISTS agent_runs(
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, agent TEXT, attempt INT,
    latency_ms REAL, tokens_in INT, tokens_out INT, cost_estimate REAL,
    outcome TEXT, correct INT, schema_retries INT, tool_calls INT,
    hitl_rounds INT, hit_iteration_cap INT, uncertainty_planted INT,
    uncertainty_surfaced INT, confidence REAL, detail_json TEXT
);
CREATE TABLE IF NOT EXISTS hitl_events(
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, agent TEXT, round INT,
    n_questions INT, answer_blank INT
);
CREATE TABLE IF NOT EXISTS pricing(
    model TEXT PRIMARY KEY, input_per_1k REAL, output_per_1k REAL
);
"""


class MetricsDB:
    """Small SQLite repository with one connection per operation."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def insert_run(self, **values: Any) -> None:
        self._insert("runs", values)

    def update_run(self, run_id: str, **values: Any) -> None:
        self._update("runs", "run_id", run_id, values)

    def insert_agent_run(self, **values: Any) -> int:
        return self._insert("agent_runs", values)

    def update_correct(self, run_id: str, correct: bool) -> None:
        self.update_run(run_id, pipeline_correct=int(correct))

    def insert_hitl_event(self, **values: Any) -> int:
        return self._insert("hitl_events", values)

    def count_agent_runs(self, run_id: str, agent: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM agent_runs WHERE run_id = ? AND agent = ?",
                (run_id, agent),
            ).fetchone()
        return int(row["count"])

    def load_pricing(self, pricing_path: str | Path) -> dict[str, dict[str, float]]:
        with Path(pricing_path).open(encoding="utf-8") as pricing_file:
            data = yaml.safe_load(pricing_file) or {}
        models = data.get("models", {})
        for model, prices in models.items():
            with self.connect() as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO pricing(model, input_per_1k, output_per_1k) VALUES (?, ?, ?)",
                    (model, prices.get("input_per_1k", 0.0), prices.get("output_per_1k", 0.0)),
                )
        return models

    def _insert(self, table: str, values: dict[str, Any]) -> int:
        if not values:
            raise ValueError("insert requires values")
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        normalized = {
            key: json.dumps(value) if isinstance(value, (dict, list)) else value
            for key, value in values.items()
        }
        with self.connect() as connection:
            cursor = connection.execute(
                f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
                tuple(normalized.values()),
            )
            return int(cursor.lastrowid)

    def _update(self, table: str, key: str, key_value: Any, values: dict[str, Any]) -> None:
        if not values:
            return
        assignments = ", ".join(f"{column} = ?" for column in values)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE {table} SET {assignments} WHERE {key} = ?",
                (*values.values(), key_value),
            )


def create_db(path: str | Path) -> MetricsDB:
    return MetricsDB(path)