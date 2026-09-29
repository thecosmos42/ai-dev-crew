"""Pure deterministic review checks."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterable

from ..schemas import CoverageGap, Violation


def check_coverage(
    coverage: dict[str, float], standards: dict,
) -> tuple[list[CoverageGap], list[Violation]]:
    gaps: list[CoverageGap] = []
    violations: list[Violation] = []
    coverage_config = standards.get("coverage", {})
    modules = coverage_config.get("modules", {})
    default_min = float(coverage_config.get("default_min", 0))
    for filename, actual in coverage.items():
        normalized = filename.replace("\\", "/")
        module_rule = modules.get(normalized, {})
        required = float(module_rule.get("min", default_min))
        if actual < required:
            sensitive = bool(module_rule.get("sensitive", False))
            gaps.append(CoverageGap(file=normalized, required=required, actual=actual, sensitive=sensitive))
            violations.append(
                Violation(
                    rule="coverage.below_threshold",
                    file=normalized,
                    detail=f"coverage {actual:.2f}% is below required {required:.2f}%",
                    severity="error",
                    source="code",
                )
            )
    return gaps, violations


def check_naming(
    changed_py_files: Iterable[tuple[str | Path | None, str | Path]],
    standards: dict,
) -> list[Violation]:
    violations: list[Violation] = []
    for baseline_path, work_path in changed_py_files:
        work = Path(work_path)
        baseline_names = _names_from_file(Path(baseline_path)) if baseline_path and Path(baseline_path).exists() else set()
        tree = ast.parse(work.read_text(encoding="utf-8"))
        relative = work.as_posix()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name not in baseline_names:
                if not _is_snake_case(node.name):
                    violations.append(_violation("naming.function_snake_case", relative, node.name, "error"))
            elif isinstance(node, ast.ClassDef) and node.name not in baseline_names:
                if not _is_pascal_case(node.name):
                    violations.append(_violation("naming.class_pascal_case", relative, node.name, "error"))
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                names = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in names:
                    if isinstance(target, ast.Name) and target.id not in baseline_names and _looks_constant(target.id):
                        if not _is_upper_snake(target.id):
                            violations.append(_violation("naming.constant_upper_snake", relative, target.id, "error"))
    return violations


def check_test_tampering(baseline: str | Path, work: str | Path) -> list[Violation]:
    baseline_tests = _test_files(Path(baseline))
    work_tests = _test_files(Path(work))
    violations: list[Violation] = []
    for relative, baseline_file in baseline_tests.items():
        work_file = work_tests.get(relative)
        if work_file is None:
            violations.append(_violation("tests.tampering", relative, "baseline test file deleted", "error"))
            continue
        baseline_tree = ast.parse(baseline_file.read_text(encoding="utf-8"))
        work_tree = ast.parse(work_file.read_text(encoding="utf-8"))
        if _count_test_functions(work_tree) < _count_test_functions(baseline_tree):
            violations.append(_violation("tests.tampering", relative, "test functions were deleted", "error"))
        if _count_nodes(work_tree, ast.Assert) < _count_nodes(baseline_tree, ast.Assert):
            violations.append(_violation("tests.tampering", relative, "assertions were removed", "error"))
        if _count_skip_or_xfail(work_tree) > _count_skip_or_xfail(baseline_tree):
            violations.append(_violation("tests.tampering", relative, "skip or xfail was added", "error"))
    for relative, work_file in work_tests.items():
        if relative not in baseline_tests:
            tree = ast.parse(work_file.read_text(encoding="utf-8"))
            if _contains_skip_or_xfail(tree):
                violations.append(_violation("tests.tampering", relative, "new skip or xfail added", "error"))
    return violations


def check_untested_public_functions(baseline: str | Path, work: str | Path) -> list[Violation]:
    baseline_root = Path(baseline)
    work_root = Path(work)
    baseline_names = _public_functions(baseline_root)
    test_text = "\n".join(path.read_text(encoding="utf-8") for path in _test_files(work_root).values())
    violations: list[Violation] = []
    for path in work_root.rglob("*.py"):
        if "tests" in path.parts or "__pycache__" in path.parts:
            continue
        for name in _public_functions_in_file(path):
            if name not in baseline_names and not re.search(rf"\b{re.escape(name)}\b", test_text):
                violations.append(_violation("tests.untested_public_function", path.relative_to(work_root).as_posix(), name, "warning"))
    return violations


def _safe_violation(rule: str, file: str, detail: str, severity: str) -> Violation:
    return Violation(rule=rule, file=file, detail=detail, severity=severity, source="code")


_violation = _safe_violation


def _names_from_file(path: Path) -> set[str]:
    if not path.exists():
        return set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {
        node.name for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _public_functions(root: Path) -> set[str]:
    names: set[str] = set()
    for path in root.rglob("*.py"):
        if "tests" not in path.parts and "__pycache__" not in path.parts:
            names.update(_public_functions_in_file(path))
    return names


def _public_functions_in_file(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
    }


def _test_files(root: Path) -> dict[str, Path]:
    return {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*.py")
        if "tests" in path.parts and path.name.startswith("test_")
    }


def _count_test_functions(tree: ast.AST) -> int:
    return sum(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
        for node in ast.walk(tree)
    )


def _count_nodes(tree: ast.AST, node_type: type[ast.AST]) -> int:
    return sum(isinstance(node, node_type) for node in ast.walk(tree))


def _contains_skip_or_xfail(tree: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Attribute) and node.attr in {"skip", "xfail"}
        for node in ast.walk(tree)
    )


def _count_skip_or_xfail(tree: ast.AST) -> int:
    return sum(
        isinstance(node, ast.Attribute) and node.attr in {"skip", "xfail"}
        for node in ast.walk(tree)
    )


def _looks_constant(name: str) -> bool:
    return any(character.isupper() for character in name)


def _is_snake_case(name: str) -> bool:
    return bool(re.fullmatch(r"[a-z_][a-z0-9_]*", name))


def _is_pascal_case(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Za-z0-9]*", name))


def _is_upper_snake(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9_]*", name))