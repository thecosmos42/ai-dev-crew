from pathlib import Path

from langchain_core.messages import AIMessage
from langgraph.types import Command

from sdlc_agents.config import Settings
from sdlc_agents.graph import build_graph
from sdlc_agents.schemas import Ticket
from sdlc_agents.state import PipelineState


ROOT = Path(__file__).parents[1]
BASELINE = ROOT / "loan_repo"


def call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


def clean_design() -> AIMessage:
    return call(
        "submit_design",
        {
            "summary": "Implement the change.",
            "affected_modules": ["loan_calc/rates.py"],
            "approach": "Update the rates module.",
            "edge_cases": ["Boundary value"],
            "test_scenarios": ["New behavior"],
            "confidence": 0.9,
        },
        "design",
    )


def ambiguous_design() -> AIMessage:
    return call(
        "submit_design",
        {
            "summary": "Need clarification.",
            "affected_modules": ["loan_calc/rates.py"],
            "approach": "Wait for a policy decision.",
            "edge_cases": [],
            "test_scenarios": [],
            "open_questions": [{"question": "Which threshold?", "why_blocking": "It changes the implementation."}],
            "ambiguity_flags": [{"type": "vague", "detail": "The threshold is unspecified."}],
            "confidence": 0.3,
        },
        "ambiguous",
    )


def finish_change(call_id: str = "finish") -> list[AIMessage]:
    content = (BASELINE / "loan_calc" / "rates.py").read_text(encoding="utf-8") + f"\n# {call_id}\n"
    return [
        call("write_file", {"path": "loan_calc/rates.py", "content": content}, "write-" + call_id),
        call("finish", {"summary": "Updated rates."}, call_id),
    ]


def approve_review(call_id: str = "review") -> AIMessage:
    return call(
        "submit_review",
        {
            "risk_level": "low",
            "violations": [],
            "missing_coverage": [],
            "test_summary": {"passed": 33, "failed": 0, "total": 33},
            "approval_decision": "approve",
            "rationale": "Approved.",
        },
        call_id,
    )


def initial_state(tmp_path: Path, run_id: str) -> PipelineState:
    return PipelineState(
        run_id=run_id,
        ticket=Ticket(id="T1", title="Rate", description="Update rate", acceptance_criteria=["Update rate"]),
        repo_path=BASELINE,
        baseline_path=BASELINE,
        max_dev_retries=1,
    )


def invoke(graph, state: PipelineState):
    return graph.invoke(state, {"configurable": {"thread_id": state.run_id}})


def test_graph_clean_path(tmp_path: Path) -> None:
    from tests.conftest import ScriptedLLM

    llm = ScriptedLLM([clean_design(), *finish_change(), approve_review()])
    graph = build_graph(llm, Settings(sdlc_db_path=tmp_path / "clean.db", runs_dir=tmp_path / "runs"))
    result = invoke(graph, initial_state(tmp_path, "clean"))
    assert result["pipeline_outcome"] == "approved"


def test_graph_design_hitl_then_resume(tmp_path: Path) -> None:
    from tests.conftest import ScriptedLLM

    llm = ScriptedLLM([ambiguous_design(), clean_design(), *finish_change("hitl"), approve_review("hitl-review")])
    graph = build_graph(llm, Settings(sdlc_db_path=tmp_path / "hitl.db", runs_dir=tmp_path / "runs"))
    state = initial_state(tmp_path, "hitl")
    config = {"configurable": {"thread_id": state.run_id}}
    interrupted = graph.invoke(state, config)
    assert "__interrupt__" in interrupted
    resumed = graph.invoke(Command(resume="Use the existing threshold."), config)
    assert resumed["pipeline_outcome"] == "approved"
    assert resumed["human_qa"][0].answer == "Use the existing threshold."


def test_graph_unresolved_hitl_after_two_rounds(tmp_path: Path) -> None:
    from tests.conftest import ScriptedLLM

    llm = ScriptedLLM([ambiguous_design(), ambiguous_design(), ambiguous_design()])
    graph = build_graph(llm, Settings(sdlc_db_path=tmp_path / "unresolved.db", runs_dir=tmp_path / "runs", max_hitl_rounds=2))
    state = initial_state(tmp_path, "unresolved")
    config = {"configurable": {"thread_id": state.run_id}}
    first = graph.invoke(state, config)
    assert "__interrupt__" in first
    second = graph.invoke(Command(resume="I don't know."), config)
    assert "__interrupt__" in second
    final = graph.invoke(Command(resume="I don't know."), config)
    assert final["pipeline_outcome"] == "needs_human_unresolved"


def test_graph_blocked_dev(tmp_path: Path) -> None:
    from tests.conftest import ScriptedLLM

    blocked = call("report_blocked", {"reason": "conflicting callers", "answerable_by_human": False}, "blocked")
    llm = ScriptedLLM([clean_design(), blocked])
    graph = build_graph(llm, Settings(sdlc_db_path=tmp_path / "blocked.db", runs_dir=tmp_path / "runs"))
    result = invoke(graph, initial_state(tmp_path, "blocked"))
    assert result["pipeline_outcome"] == "blocked"


def test_graph_reject_retry_then_approve(tmp_path: Path) -> None:
    from tests.conftest import ScriptedLLM

    reject = call(
        "submit_review",
        {"risk_level": "medium", "violations": [], "missing_coverage": [], "test_summary": {"passed": 33, "failed": 0, "total": 33}, "approval_decision": "reject", "rationale": "Needs changes."},
        "reject",
    )
    llm = ScriptedLLM([clean_design(), *finish_change("first"), reject, *finish_change("second"), approve_review("approved")])
    graph = build_graph(llm, Settings(sdlc_db_path=tmp_path / "retry.db", runs_dir=tmp_path / "runs"))
    result = invoke(graph, initial_state(tmp_path, "retry"))
    assert result["pipeline_outcome"] == "approved"
    assert result["dev_attempts"] == 2


def test_graph_reject_retries_exhausted(tmp_path: Path) -> None:
    from tests.conftest import ScriptedLLM

    reject = call(
        "submit_review",
        {"risk_level": "medium", "violations": [], "missing_coverage": [], "test_summary": {"passed": 33, "failed": 0, "total": 33}, "approval_decision": "reject", "rationale": "Rejected."},
        "reject",
    )
    llm = ScriptedLLM([clean_design(), *finish_change("once"), reject])
    graph = build_graph(llm, Settings(sdlc_db_path=tmp_path / "exhausted.db", runs_dir=tmp_path / "runs", max_dev_retries=0))
    state = initial_state(tmp_path, "exhausted")
    state.max_dev_retries = 0
    result = invoke(graph, state)
    assert result["pipeline_outcome"] == "rejected"


def test_graph_error_path(tmp_path: Path) -> None:
    from tests.conftest import ScriptedLLM

    invalid = call("submit_design", {"summary": "bad"}, "invalid")
    llm = ScriptedLLM([invalid, invalid, invalid])
    graph = build_graph(llm, Settings(sdlc_db_path=tmp_path / "error.db", runs_dir=tmp_path / "runs", max_schema_retries=2))
    result = invoke(graph, initial_state(tmp_path, "error"))
    assert result["pipeline_outcome"] == "error"