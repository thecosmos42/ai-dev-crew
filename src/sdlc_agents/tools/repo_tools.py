"""Scoped repository tools exposed to development agents."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool

MAX_FILE_SIZE = 200 * 1024


class RepoTools:
    """Read and write a repository without relying on a global repo path."""

    def __init__(self, repo_root: str | Path):
        self.repo_root = Path(repo_root).resolve()

    def list_files(self) -> str:
        files = [
            path.relative_to(self.repo_root).as_posix()
            for path in self.repo_root.rglob("*.py")
            if "__pycache__" not in path.parts
        ]
        return "\n".join(sorted(files))

    def read_file(self, path: str) -> str:
        target, error = self._safe_path(path)
        if error:
            return error
        if not target.exists() or not target.is_file():
            return f"ERROR: file does not exist: {path}"
        try:
            content = target.read_text(encoding="utf-8")
        except OSError as exc:
            return f"ERROR: could not read {path}: {exc}"
        if len(content.encode("utf-8")) > MAX_FILE_SIZE:
            return f"ERROR: file exceeds {MAX_FILE_SIZE} bytes: {path}"
        return content

    def search_code(self, pattern: str) -> str:
        try:
            matcher = re.compile(pattern)
        except re.error:
            matcher = re.compile(re.escape(pattern))
        hits: list[str] = []
        for relative_path in self.list_files().splitlines():
            content = self.read_file(relative_path)
            if content.startswith("ERROR:"):
                continue
            for line_number, line in enumerate(content.splitlines(), start=1):
                if matcher.search(line):
                    hits.append(f"{relative_path}:{line_number}: {line}")
                    if len(hits) >= 50:
                        return "\n".join(hits)
        return "\n".join(hits)

    def write_file(self, path: str, content: str) -> str:
        if not path or Path(path).is_absolute() or ".." in Path(path).parts:
            return f"ERROR: path must be a relative .py path inside the repository: {path}"
        if Path(path).suffix != ".py":
            return f"ERROR: only .py files may be written: {path}"
        target, error = self._safe_path(path)
        if error:
            return error
        if len(content.encode("utf-8")) > MAX_FILE_SIZE:
            return f"ERROR: content exceeds {MAX_FILE_SIZE} bytes: {path}"
        try:
            ast.parse(content, filename=path)
        except SyntaxError as exc:
            return f"ERROR: invalid Python syntax in {path}: {exc}"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            return f"ERROR: could not write {path}: {exc}"
        return f"OK: wrote {path}"

    def as_tools(self) -> list[StructuredTool]:
        return [
            StructuredTool.from_function(
                func=self.list_files,
                name="list_files",
                description="List Python files in the scoped repository.",
            ),
            StructuredTool.from_function(
                func=self.read_file,
                name="read_file",
                description="Read a UTF-8 file in the scoped repository.",
            ),
            StructuredTool.from_function(
                func=self.search_code,
                name="search_code",
                description="Search Python source with a regular expression.",
            ),
            StructuredTool.from_function(
                func=self.write_file,
                name="write_file",
                description="Write syntactically valid Python inside the scoped repository.",
            ),
        ]

    def _safe_path(self, path: str) -> tuple[Path, str | None]:
        candidate = self.repo_root / path
        if Path(path).is_absolute() or ".." in Path(path).parts:
            return candidate, f"ERROR: path escapes repository: {path}"
        for part in Path(path).parts:
            current = self.repo_root.joinpath(*Path(path).parts[: Path(path).parts.index(part) + 1])
            if current.is_symlink():
                return candidate, f"ERROR: symlink paths are not allowed: {path}"
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.repo_root)
        except ValueError:
            return resolved, f"ERROR: path escapes repository: {path}"
        return resolved, None


def repo_tools(repo_root: str | Path) -> RepoTools:
    return RepoTools(repo_root)