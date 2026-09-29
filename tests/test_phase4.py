import json
from pathlib import Path

from langchain_core.messages import AIMessage

from sdlc_agents.agents.base import run_tool_loop
from sdlc_agents.agents.design_agent import run_design_agent
from sdlc_agents.config import Settings
from sdlc_agents.metrics.tracker import UsageTracker
from sdlc_agents.schemas import Ticket
from sdlc_agents.tools.repo_tools import RepoTools


def design_message(module: str = "loan_calc/rates.py") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "submit_design",
                "args": {
                    "summary": "Add a rate tier",
                    "affected_modules": [module],
                    "approach": "Add the tier and preserve existing behavior.",
                    "edge_cases": ["Boundary score"],
                    "test_scenarios": ["Scores below and at the boundary"],
                    "confidence": 0.95,
                },
                "id": "design-1",
                "type": "tool_call",
            }
        ],
    )


def test_design_agent_happy_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "loan_calc").mkdir(parents=True)
    (repo / "loan_calc" / "rates.py").write_text("", encoding="utf-8")
    ticket = Ticket(id="T1", title="Rate", description="Add rate", acceptance_criteria=["Add tier"])
    from tests.conftest import ScriptedLLM

    design = run_design_agent(ScriptedLLM([design_message()]), ticket, repo)
    assert design is not None
    assert design.affected_modules == ["loan_calc/rates.py"]


def test_design_agent_retries_invalid_module(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "loan_calc").mkdir(parents=True)
    (repo / "loan_calc" / "rates.py").write_text("", encoding="utf-8")
    ticket = Ticket(id="T1", title="Rate", description="Add rate", acceptance_criteria=["Add tier"])
    from tests.conftest import ScriptedLLM

    llm = ScriptedLLM([design_message("loan_calc/missing.py"), design_message()])
    tracker = UsageTracker()
    design = run_design_agent(llm, ticket, repo, tracker=tracker)
    assert design is not None
    assert tracker.schema_retries == 1


def test_design_agent_iteration_cap(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    ticket = Ticket(id="T1", title="Rate", description="Add rate", acceptance_criteria=["Add tier"])
    from tests.conftest import ScriptedLLM

    design = run_design_agent(
        ScriptedLLM([AIMessage(content="no tool call")]),
        ticket,
        repo,
        settings=Settings(max_tool_iterations=1),
    )
    assert design is None


def test_loop_executes_non_terminal_tool(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("value = 1\n", encoding="utf-8")
    tool = RepoTools(tmp_path).as_tools()[0]
    from tests.conftest import ScriptedLLM

    response = AIMessage(
        content="",
        tool_calls=[{"name": "list_files", "args": {}, "id": "list-1", "type": "tool_call"}],
    )
    terminal = design_message()
    result = run_tool_loop(
        ScriptedLLM([response, terminal]),
        "system",
        "user",
        [tool],
        {"submit_design": __import__("sdlc_agents.schemas", fromlist=["DesignDoc"]).DesignDoc},
        3,
        UsageTracker(),
    )
    assert result is not None