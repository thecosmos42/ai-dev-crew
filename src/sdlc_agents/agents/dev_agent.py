"""Development Agent with isolated working-copy and diff-derived results."""

from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..config import Settings
from ..llm import LLMClient
from ..metrics.tracker import UsageTracker, get_current_tracker
from ..schemas import DesignDoc, DevResult, HumanQA, OpenQuestion
from ..tools.diffing import make_diff
from ..tools.repo_tools import RepoTools
from .base import run_tool_loop

DEV_SYSTEM = """You are the Development Agent. Implement the approved design using the scoped repository tools.
Read every file before changing it and search callers before changing existing functions.
Never edit tests when the ticket forbids it. Finish with exactly one terminal call: finish or report_blocked.
Report blocked when an existing function change conflicts with callers outside the design scope.
Never fabricate a diff or claim success without writing a real change."""


class FinishRequest(BaseModel):
    summary: str


class BlockedRequest(BaseModel):
    reason: str
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    answerable_by_human: bool = False


def prepare_working_copy(
    baseline_path: str | Path,
    runs_dir: str | Path,
    run_id: str,
) -> Path:
    destination = Path(runs_dir) / run_id / "repo"
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(baseline_path, destination)
    return destination


def run_development_agent(
    llm: LLMClient,
    design: DesignDoc,
    baseline_path: str | Path,
    runs_dir: str | Path,
    run_id: str,
    human_qa: list[HumanQA] | None = None,
    review_feedback: str | None = None,
    settings: Settings | None = None,
    tracker: UsageTracker | None = None,
) -> DevResult:
    active_settings = settings or Settings()
    active_tracker = tracker or get_current_tracker() or UsageTracker()
    work_path = prepare_working_copy(baseline_path, runs_dir, run_id)
    repository = RepoTools(work_path)
    user = json.dumps(
        {
            "design": design.model_dump(),
            "human_qa": [qa.model_dump() for qa in human_qa or []] or "none",
            "review_feedback": review_feedback or "none",
        },
        separators=(",", ":"),
    )
    result = run_tool_loop(
        llm=llm,
        system=DEV_SYSTEM,
        user=user,
        tools=repository.as_tools(),
        terminal_models={"finish": FinishRequest, "report_blocked": BlockedRequest},
        max_iters=active_settings.max_tool_iterations,
        tracker=active_tracker,
        max_schema_retries=active_settings.max_schema_retries,
    )
    terminal_name = active_tracker.details.get("terminal_tool")
    if result is None:
        return DevResult(status="blocked", blocked_reason="iteration_cap", iteration_cap_hit=True)
    if terminal_name == "report_blocked" and isinstance(result, BlockedRequest):
        return DevResult(
            status="blocked",
            blocked_reason=result.reason,
            open_questions=result.open_questions,
            answerable_by_human=result.answerable_by_human,
        )
    if not isinstance(result, FinishRequest):
        return DevResult(status="blocked", blocked_reason="invalid_terminal_result")

    diff, files_changed = make_diff(baseline_path, work_path)
    if not diff:
        return DevResult(status="blocked", blocked_reason="empty_diff", notes=result.summary)
    return DevResult(
        status="success",
        files_changed=files_changed,
        tests_added=_new_test_functions(baseline_path, work_path),
        diff=diff,
        notes=result.summary,
    )


def _new_test_functions(baseline_path: str | Path, work_path: str | Path) -> list[str]:
    baseline_names = _test_function_names(Path(baseline_path))
    work_names = _test_function_names(Path(work_path))
    return sorted(work_names - baseline_names)


def _test_function_names(root: Path) -> set[str]:
    names: set[str] = set()
    for path in root.rglob("*.py"):
        if "tests" not in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        names.update(
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
        )
    return names


development_agent = run_development_agent