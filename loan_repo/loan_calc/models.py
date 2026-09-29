from dataclasses import dataclass, field


@dataclass
class Applicant:
    applicant_id: str
    age: int
    monthly_income: float
    monthly_debt_payments: float
    credit_score: int
    employment_months: int
    employment_type: str
    requested_amount: float
    term_months: int
    recent_delinquencies: int = 0


@dataclass
class LoanDecision:
    approved: bool
    reasons: list[str] = field(default_factory=list)
    rate: float | None = None
    risk_score: int = 0