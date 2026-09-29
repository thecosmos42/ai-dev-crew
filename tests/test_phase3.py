import shutil
from pathlib import Path

import pytest

from sdlc_agents.schemas import CoverageGap
from sdlc_agents.tools.checks import (
    check_coverage,
    check_naming,
    check_test_tampering,
    check_untested_public_functions,
)
from sdlc_agents.tools.diffing import make_diff
from sdlc_agents.tools.repo_tools import RepoTools
from sdlc_agents.tools.test_runner import run_tests


def test_repo_tools_list_read_search_and_write(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("def existing():\n    return 1\n", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "ignored.py").write_text("", encoding="utf-8")
    tools = RepoTools(tmp_path)

    assert tools.list_files() == "module.py"
    assert "existing" in tools.search_code("existing")
    assert tools.read_file("missing.py").startswith("ERROR:")
    assert tools.write_file("new.py", "def new_function():\n    return 2\n").startswith("OK:")
    assert "new.py" in tools.list_files()
    assert len(tools.as_tools()) == 4


@pytest.mark.parametrize("path", ["../outside.py", "/etc/passwd"])
def test_repo_tools_rejects_escape_paths(tmp_path: Path, path: str) -> None:
    tools = RepoTools(tmp_path)
    assert tools.write_file(path, "x = 1").startswith("ERROR:")
    assert tools.read_file(path).startswith("ERROR:")


def test_repo_tools_rejects_symlink(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_phase3.py"
    outside.write_text("x = 1", encoding="utf-8")
    link = tmp_path / "link.py"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    assert RepoTools(tmp_path).write_file("link.py", "x = 2").startswith("ERROR:")


def test_repo_tools_rejects_invalid_python(tmp_path: Path) -> None:
    result = RepoTools(tmp_path).write_file("broken.py", "def broken(:\n")
    assert result.startswith("ERROR: invalid Python syntax")


def test_make_diff_reports_changes_new_and_deleted_files(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    work = tmp_path / "work"
    baseline.mkdir()
    work.mkdir()
    (baseline / "changed.py").write_text("old\n", encoding="utf-8")
    (baseline / "deleted.py").write_text("gone\n", encoding="utf-8")
    (work / "changed.py").write_text("new\n", encoding="utf-8")
    (work / "added.py").write_text("added\n", encoding="utf-8")
    (work / "coverage.json").write_text("ignored", encoding="utf-8")
    diff, files = make_diff(baseline, work)
    assert files == ["added.py", "changed.py", "deleted.py"]
    assert "deleted.py" in diff and "added.py" in diff and "-old" in diff and "+new" in diff
    assert "coverage.json" not in diff


def test_run_tests_returns_summary_and_coverage() -> None:
    result = run_tests(Path(__file__).parents[1] / "loan_repo")
    assert result.summary.failed == 0
    assert result.summary.total == 33
    assert result.coverage["loan_calc/rates.py"] >= 85


def test_check_coverage_reports_sensitive_gap() -> None:
    gaps, violations = check_coverage(
        {"loan_calc/risk_scoring.py": 80.0, "loan_calc/models.py": 80.0},
        {
            "coverage": {
                "default_min": 75,
                "modules": {"loan_calc/risk_scoring.py": {"min": 90, "sensitive": True}},
            }
        },
    )
    assert gaps == [CoverageGap(file="loan_calc/risk_scoring.py", required=90, actual=80, sensitive=True)]
    assert [violation.rule for violation in violations] == ["coverage.below_threshold"]


def test_check_naming_flags_only_new_camel_case_names(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.py"
    work = tmp_path / "work.py"
    baseline.write_text("def existing_name():\n    pass\n", encoding="utf-8")
    work.write_text(
        "def existing_name():\n    pass\n\ndef newFunction():\n    pass\n\nclass badClass:\n    pass\n\nbad_CONST = 1\n",
        encoding="utf-8",
    )
    violations = check_naming([(baseline, work)], {})
    assert {violation.rule for violation in violations} == {
        "naming.function_snake_case",
        "naming.class_pascal_case",
        "naming.constant_upper_snake",
    }


def test_check_test_tampering_detects_removed_assertions(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    work = tmp_path / "work"
    for root in (baseline, work):
        (root / "tests").mkdir(parents=True)
    original = "def test_one():\n    assert 1 == 1\n    assert 2 == 2\n"
    reduced = "def test_one():\n    assert 1 == 1\n"
    (baseline / "tests" / "test_sample.py").write_text(original, encoding="utf-8")
    (work / "tests" / "test_sample.py").write_text(reduced, encoding="utf-8")
    violations = check_test_tampering(baseline, work)
    assert any(violation.rule == "tests.tampering" for violation in violations)


def test_check_test_tampering_detects_deleted_file(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    work = tmp_path / "work"
    (baseline / "tests").mkdir(parents=True)
    (work / "tests").mkdir(parents=True)
    (baseline / "tests" / "test_deleted.py").write_text("def test_one():\n    assert True\n", encoding="utf-8")
    assert check_test_tampering(baseline, work)


def test_check_untested_public_function(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    work = tmp_path / "work"
    (baseline / "pkg").mkdir(parents=True)
    (work / "pkg").mkdir(parents=True)
    (baseline / "pkg" / "module.py").write_text("def old_function():\n    pass\n", encoding="utf-8")
    (work / "pkg" / "module.py").write_text(
        "def old_function():\n    pass\n\ndef new_function():\n    pass\n", encoding="utf-8"
    )
    assert check_untested_public_functions(baseline, work)[0].rule == "tests.untested_public_function"