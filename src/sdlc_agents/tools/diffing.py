"""Deterministic unified diffs between repository trees."""

from __future__ import annotations

import difflib
from pathlib import Path

IGNORED_NAMES = {"__pycache__", ".pytest_cache", ".coverage", "coverage.json"}


def _walk_files(root: Path) -> set[str]:
    paths: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file() or any(part in IGNORED_NAMES for part in path.parts):
            continue
        if path.suffix == ".xml" or path.name.endswith(".xml"):
            continue
        paths.add(path.relative_to(root).as_posix())
    return paths


def make_diff(baseline: str | Path, work: str | Path) -> tuple[str, list[str]]:
    baseline_root = Path(baseline)
    work_root = Path(work)
    changed: list[str] = []
    chunks: list[str] = []
    for relative_path in sorted(_walk_files(baseline_root) | _walk_files(work_root)):
        before_path = baseline_root / relative_path
        after_path = work_root / relative_path
        before = before_path.read_text(encoding="utf-8").splitlines(keepends=True) if before_path.exists() else []
        after = after_path.read_text(encoding="utf-8").splitlines(keepends=True) if after_path.exists() else []
        if before == after:
            continue
        changed.append(relative_path)
        chunks.extend(
            difflib.unified_diff(
                before,
                after,
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
            )
        )
    return "".join(chunks), changed