"""Validated data contracts exchanged by the pipeline agents."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Ticket(BaseModel):
    id: str
    title: str
    description: str
    acceptance_criteria: list[str]

    @field_validator("acceptance_criteria")
    @classmethod
    def criteria_must_be_nonempty(cls, values: list[str]) -> list[str]:
        if not values or any(not criterion.strip() for criterion in values):
            raise ValueError("acceptance_criteria must contain non-blank values")
        return values


class OpenQuestion(BaseModel):
    question: str
    why_blocking: str

    @field_validator("question", "why_blocking")
    @classmethod
    def text_must_be_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question fields must be non-blank")
        return value


class AmbiguityFlag(BaseModel):
    type: Literal["vague", "contradictory", "missing_dependency"]
    detail: str


class DesignDoc(BaseModel):
    summary: str
    affected_modules: list[str]
    new_files: list[str] = Field(default_factory=list)
    approach: str
    edge_cases: list[str]
    test_scenarios: list[str]
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    ambiguity_flags: list[AmbiguityFlag] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def flags_require_questions(self) -> "DesignDoc":
        if self.ambiguity_flags and not self.open_questions:
            raise ValueError("ambiguity flags require at least one open question")
        if len(self.open_questions) > 3:
            raise ValueError("at most three open questions are allowed")
        return self


class DevResult(BaseModel):
    status: Literal["success", "blocked"]
    files_changed: list[str] = Field(default_factory=list)
    tests_added: list[str] = Field(default_factory=list)
    diff: str = ""
    blocked_reason: str | None = None
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    answerable_by_human: bool = False
    iteration_cap_hit: bool = False
    notes: str = ""


class Violation(BaseModel):
    rule: str
    file: str | None = None
    detail: str
    severity: Literal["error", "warning"]
    source: Literal["code", "llm"]


class CoverageGap(BaseModel):
    file: str
    required: float
    actual: float
    sensitive: bool


class TestSummary(BaseModel):
    passed: int
    failed: int
    total: int


class ReviewResult(BaseModel):
    risk_level: Literal["low", "medium", "high"]
    violations: list[Violation]
    missing_coverage: list[CoverageGap]
    test_summary: TestSummary
    approval_decision: Literal["approve", "reject"]
    rationale: str
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    gate_overrides: list[str] = Field(default_factory=list)


class HumanQA(BaseModel):
    agent: str
    round: int
    questions: list[OpenQuestion]
    answer: str


PipelineOutcome = Literal[
    "approved",
    "rejected",
    "blocked",
    "needs_human_unresolved",
    "error",
]