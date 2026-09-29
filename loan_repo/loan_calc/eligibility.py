from .dti import calculate_dti
from .income_verification import verify_income
from .models import Applicant, LoanDecision
from .rates import pick_rate
from .risk_scoring import score_applicant

MIN_CREDIT_SCORE = 580
MAX_DTI = 0.43


def evaluate(applicant: Applicant) -> LoanDecision:
    """Evaluate an applicant against the baseline loan policy."""

    risk_score = score_applicant(applicant)
    reasons: list[str] = []
    if applicant.age < 18:
        reasons.append("underage")
    if applicant.credit_score < MIN_CREDIT_SCORE:
        reasons.append("credit_score_below_minimum")
    if applicant.monthly_income <= 0:
        reasons.append("invalid_income")
        dti = 1.0
    else:
        dti = calculate_dti(applicant.monthly_debt_payments, applicant.monthly_income)
    if dti > MAX_DTI:
        reasons.append("dti_above_maximum")
    if not verify_income(applicant):
        reasons.append("income_not_verified")
    if risk_score < 50:
        reasons.append("risk_score_below_minimum")
    if reasons:
        return LoanDecision(approved=False, reasons=reasons, risk_score=risk_score)
    return LoanDecision(approved=True, reasons=[], rate=pick_rate(applicant), risk_score=risk_score)