from pathlib import Path

from langchain_core.messages import AIMessage

from sdlc_agents.agents.dev_agent import run_development_agent
from sdlc_agents.config import Settings
from sdlc_agents.schemas import DesignDoc


def design_for(module: str) -> DesignDoc:
    return DesignDoc(
        summary="Implement a small change",
        affected_modules=[module],
        approach="Edit the target module.",
        edge_cases=["Boundary input"],
        test_scenarios=["Verify the new behavior"],
        confidence=0.9,
    )


def tool_message(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


def test_development_success_derives_diff_and_tests(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    (baseline / "loan_calc").mkdir(parents=True)
    (baseline / "tests").mkdir()
    (baseline / "loan_calc" / "rates.py").write_text("VALUE = 1\n", encoding="utf-8")
    (baseline / "tests" / "test_rates.py").write_text("def test_old():\n    assert True\n", encoding="utf-8")
    response_write = tool_message("write_file", {"path": "loan_calc/rates.py", "content": "VALUE = 2\n"}, "w1")
    response_finish = tool_message("finish", {"summary": "Updated the value."}, "f1")
    from tests.conftest import ScriptedLLM

    result = run_development_agent(
        ScriptedLLM([response_write, response_finish]),
        design_for("loan_calc/rates.py"),
        baseline,
        tmp_path / "runs",
        "run-success",
    )
    assert result.status == "success"
    assert result.files_changed == ["loan_calc/rates.py"]
    assert "-VALUE = 1" in result.diff and "+VALUE = 2" in result.diff
    assert result.tests_added == []


def test_development_blocked_reports_reason(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    (baseline / "loan_calc").mkdir(parents=True)
    (baseline / "loan_calc" / "dti.py").write_text("", encoding="utf-8")
    response = tool_message(
        "report_blocked",
        {
            "reason": "calculate_dti has three callers: eligibility.evaluate, risk_scoring.score_applicant, rates.pick_rate",
            "answerable_by_human": False,
        },
        "b1",
    )
    from tests.conftest import ScriptedLLM

    result = run_development_agent(
        ScriptedLLM([response]),
        design_for("loan_calc/dti.py"),
        baseline,
        tmp_path / "runs",
        "run-blocked",
    )
    assert result.status == "blocked"
    assert "three callers" in result.blocked_reason
    assert result.diff == ""


def test_development_empty_success_becomes_blocked(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    from tests.conftest import ScriptedLLM

    result = run_development_agent(
        ScriptedLLM([tool_message("finish", {"summary": "Nothing needed."}, "f1")]),
        design_for("missing.py"),
        baseline,
        tmp_path / "runs",
        "run-empty",
    )
    assert result.status == "blocked"
    assert result.blocked_reason == "empty_diff"


def test_development_cap_is_blocked(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    from tests.conftest import ScriptedLLM

    result = run_development_agent(
        ScriptedLLM([AIMessage(content="no terminal")]),
        design_for("missing.py"),
        baseline,
        tmp_path / "runs",
        "run-cap",
        settings=Settings(max_tool_iterations=1),
    )
    assert result.status == "blocked"
    assert result.blocked_reason == "iteration_cap"
    assert result.iteration_cap_hit


def test_working_copy_is_reused_for_retry(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    runs = tmp_path / "runs"
    from tests.conftest import ScriptedLLM

    first = run_development_agent(
        ScriptedLLM([
            tool_message("write_file", {"path": "change.py", "content": "VALUE = 1\n"}, "w1"),
            tool_message("finish", {"summary": "first"}, "f1"),
        ]),
        design_for("change.py"), baseline, runs, "retry",
    )
    second = run_development_agent(
        ScriptedLLM([tool_message("finish", {"summary": "second"}, "f2")]),
        design_for("change.py"), baseline, runs, "retry",
    )
    assert first.status == "success"
    assert second.status == "success"
    assert "+VALUE = 1" in second.diff