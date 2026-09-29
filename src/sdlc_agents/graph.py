"""LangGraph pipeline wiring, routing, and HITL handling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .agents.base import SchemaRetriesExhausted
from .agents.dev_agent import prepare_working_copy, run_development_agent
from .agents.design_agent import run_design_agent
from .agents.review_agent import run_review_agent
from .config import Settings
from .llm import LLMClient
from .metrics.db import MetricsDB
from .schemas import HumanQA
from .state import PipelineState


def after_validate(state: PipelineState | dict[str, Any]) -> str:
    return "finalize" if _value(state, "error") else "design"


def after_design(state: PipelineState | dict[str, Any]) -> str:
    if _value(state, "error"):
        return "finalize"
    design = _value(state, "design")
    if design is not None and design.open_questions:
        return "hitl"
    return "dev"


def after_hitl(state: PipelineState | dict[str, Any]) -> str:
    return "finalize" if _value(state, "pipeline_outcome") else str(_value(state, "pending_agent") or "design")


def after_dev(state: PipelineState | dict[str, Any]) -> str:
    if _value(state, "error"):
        return "finalize"
    result = _value(state, "dev_result")
    if result is None:
        return "finalize"
    if result.status == "success":
        return "review"
    rounds = _value(state, "hitl_rounds") or {}
    pending = result.answerable_by_human and rounds.get("dev", 0) < 2 and bool(result.open_questions)
    return "hitl" if pending else "finalize"


def after_review(state: PipelineState | dict[str, Any]) -> str:
    if _value(state, "error"):
        return "finalize"
    review = _value(state, "review")
    if review is None:
        return "finalize"
    rounds = _value(state, "hitl_rounds") or {}
    if review.open_questions and rounds.get("review", 0) < 2:
        return "hitl"
    if review.approval_decision == "approve":
        return "finalize"
    attempts = int(_value(state, "dev_attempts") or 0)
    max_retries = int(_value(state, "max_dev_retries") or 0)
    return "dev" if attempts < 1 + max_retries else "finalize"


def finalize(state: PipelineState | dict[str, Any]) -> dict[str, Any]:
    if _value(state, "pipeline_outcome"):
        return {}
    if _value(state, "error"):
        return {"pipeline_outcome": "error"}
    dev_result = _value(state, "dev_result")
    review = _value(state, "review")
    if dev_result is not None and dev_result.status == "blocked":
        return {"pipeline_outcome": "blocked"}
    if review is not None:
        return {"pipeline_outcome": "approved" if review.approval_decision == "approve" else "rejected"}
    return {"pipeline_outcome": "error"}


def build_graph(llm: LLMClient, settings: Settings | None = None):
    active_settings = settings or Settings()
    db = MetricsDB(active_settings.sdlc_db_path)

    def validate_node(state: PipelineState) -> dict[str, Any]:
        try:
            state.ticket
            return {}
        except Exception as exc:
            return {"error": str(exc)}

    def design_node(state: PipelineState) -> dict[str, Any]:
        try:
            design = run_design_agent(llm, state.ticket, state.repo_path, state.human_qa, active_settings)
            if design is None:
                return {"error": "design agent did not submit a design"}
            updates: dict[str, Any] = {"design": design, "pending_questions": []}
            if design.open_questions:
                updates.update({"pending_questions": design.open_questions, "pending_agent": "design"})
            return updates
        except (SchemaRetriesExhausted, Exception) as exc:
            return {"error": str(exc)}

    def hitl_node(state: PipelineState) -> dict[str, Any]:
        agent = state.pending_agent or "design"
        round_number = state.hitl_rounds.get(agent, 0)
        if round_number >= active_settings.max_hitl_rounds:
            return {"pipeline_outcome": "needs_human_unresolved"}
        answer = interrupt(
            {
                "agent": agent,
                "questions": [question.model_dump() for question in state.pending_questions],
                "round": round_number,
            }
        )
        questions = list(state.pending_questions)
        qa = HumanQA(agent=agent, round=round_number + 1, questions=questions, answer=str(answer))
        rounds = dict(state.hitl_rounds)
        rounds[agent] = round_number + 1
        if db:
            db.insert_hitl_event(
                run_id=state.run_id,
                agent=agent,
                round=round_number + 1,
                n_questions=len(questions),
                answer_blank=int(not str(answer).strip() or str(answer).strip().lower() == "i don't know."),
            )
        return {"human_qa": [qa], "hitl_rounds": rounds, "pending_questions": []}

    def dev_node(state: PipelineState) -> dict[str, Any]:
        try:
            if state.design is None:
                return {"error": "development started without a design"}
            result = run_development_agent(
                llm,
                state.design,
                state.baseline_path,
                active_settings.runs_dir,
                state.run_id,
                state.human_qa,
                state.review_feedback,
                active_settings,
            )
            work_path = prepare_working_copy(state.baseline_path, active_settings.runs_dir, state.run_id)
            updates: dict[str, Any] = {
                "dev_result": result,
                "dev_attempts": state.dev_attempts + 1,
                "repo_path": work_path,
                "pending_questions": [],
            }
            if result.open_questions:
                updates.update({"pending_questions": result.open_questions, "pending_agent": "dev"})
            return updates
        except (SchemaRetriesExhausted, Exception) as exc:
            return {"error": str(exc)}

    def review_node(state: PipelineState) -> dict[str, Any]:
        try:
            if state.design is None:
                return {"error": "review started without a design"}
            review = run_review_agent(
                llm,
                state.design,
                state.baseline_path,
                state.repo_path,
                active_settings.standards,
                active_settings,
            )
            if review is None:
                return {"error": "review agent did not submit a review"}
            updates: dict[str, Any] = {"review": review, "pending_questions": []}
            if review.open_questions:
                updates.update({"pending_questions": review.open_questions, "pending_agent": "review"})
            if review.approval_decision == "reject":
                updates["review_feedback"] = json.dumps(review.model_dump(), separators=(",", ":"))
            return updates
        except (SchemaRetriesExhausted, Exception) as exc:
            return {"error": str(exc)}

    graph = StateGraph(PipelineState)
    graph.add_node("validate", validate_node)
    graph.add_node("design", design_node)
    graph.add_node("hitl", hitl_node)
    graph.add_node("dev", dev_node)
    graph.add_node("review", review_node)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "validate")
    graph.add_conditional_edges("validate", after_validate, {"design": "design", "finalize": "finalize"})
    graph.add_conditional_edges("design", after_design, {"hitl": "hitl", "dev": "dev", "finalize": "finalize"})
    graph.add_conditional_edges("hitl", after_hitl, {"design": "design", "dev": "dev", "review": "review", "finalize": "finalize"})
    graph.add_conditional_edges("dev", after_dev, {"hitl": "hitl", "review": "review", "finalize": "finalize"})
    graph.add_conditional_edges("review", after_review, {"hitl": "hitl", "dev": "dev", "finalize": "finalize"})
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=MemorySaver())


def _value(state: PipelineState | dict[str, Any], key: str) -> Any:
    return getattr(state, key, None) if isinstance(state, PipelineState) else state.get(key)