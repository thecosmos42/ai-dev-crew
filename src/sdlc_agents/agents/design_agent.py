"""Design Agent implementation using read-only repository tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import Settings
from ..llm import LLMClient
from ..metrics.tracker import UsageTracker, get_current_tracker
from ..schemas import DesignDoc, HumanQA, Ticket
from ..tools.repo_tools import RepoTools
from .base import run_tool_loop

DESIGN_SYSTEM = """You are the Design Agent. Turn the ticket into a structured design for a small Python repository.
Use the read-only tools to inspect relevant files and callers. Finish by calling submit_design exactly once.
Do not guess when requirements are vague or contradictory: add an ambiguity flag and a blocking question.
affected_modules must contain exact existing repository paths; new files belong in new_files."""


def run_design_agent(
    llm: LLMClient,
    ticket: Ticket,
    repo_root: str | Path,
    human_qa: list[HumanQA] | None = None,
    settings: Settings | None = None,
    tracker: UsageTracker | None = None,
) -> DesignDoc | None:
    active_settings = settings or Settings()
    active_tracker = tracker or get_current_tracker() or UsageTracker()
    repository = RepoTools(repo_root)
    manifest = repository.list_files()
    answers = [qa.model_dump() for qa in human_qa or []]
    user = json.dumps(
        {
            "ticket": ticket.model_dump(),
            "repo_manifest": manifest,
            "human_qa": answers or "none",
        },
        separators=(",", ":"),
    )

    def validate_modules(design: Any) -> None:
        existing = set(manifest.splitlines())
        missing = [path for path in design.affected_modules if path not in existing]
        unexpected = [path for path in design.new_files if path in existing]
        if missing or unexpected:
            raise ValueError(
                f"affected_modules must exist and new_files must not; missing={missing}, already_exist={unexpected}"
            )

    result = run_tool_loop(
        llm=llm,
        system=DESIGN_SYSTEM,
        user=user,
        tools=repository.as_tools()[:3],
        terminal_models={"submit_design": DesignDoc},
        max_iters=active_settings.max_tool_iterations,
        tracker=active_tracker,
        terminal_validators={"submit_design": validate_modules},
        max_schema_retries=active_settings.max_schema_retries,
    )
    return result if isinstance(result, DesignDoc) else None


design_agent = run_design_agent