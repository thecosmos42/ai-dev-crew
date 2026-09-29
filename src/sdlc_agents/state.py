"""Pydantic state carried through the pipeline graph."""

import operator
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field

from .schemas import (
    DesignDoc,
    DevResult,
    HumanQA,
    OpenQuestion,
    PipelineOutcome,
    ReviewResult,
    Ticket,
)


class PipelineState(BaseModel):
    run_id: str
    ticket: Ticket
    repo_path: Path
    baseline_path: Path
    design: DesignDoc | None = None
    dev_result: DevResult | None = None
    review: ReviewResult | None = None
    review_feedback: str | None = None
    human_qa: Annotated[list[HumanQA], operator.add] = Field(default_factory=list)
    pending_questions: list[OpenQuestion] = Field(default_factory=list)
    pending_agent: str | None = None
    hitl_rounds: dict[str, int] = Field(default_factory=dict)
    dev_attempts: int = 0
    max_dev_retries: int = 1
    pipeline_outcome: PipelineOutcome | None = None
    error: str | None = None