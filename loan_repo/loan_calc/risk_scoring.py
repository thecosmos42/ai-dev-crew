from .dti import calculate_dti
from .models import Applicant


def score_applicant(applicant: Applicant) -> int:
    """Calculate a bounded risk score from credit, DTI, and employment history."""

    try:
        dti = calculate_dti(applicant.monthly_debt_payments, applicant.monthly_income)
    except ValueError:
        dti = 1.0
    credit_component = max(0.0, min(60.0, (applicant.credit_score - 300) / 7.33))
    dti_component = max(0.0, min(25.0, 25.0 - (dti * 25.0)))
    employment_component = min(15.0, max(0.0, applicant.employment_months / 24.0 * 15.0))
    return max(0, min(100, round(credit_component + dti_component + employment_component)))


def risk_bucket(score: int) -> str:
    """Map a score to a broad risk bucket."""

    if score >= 75:
        return "low"
    if score >= 50:
        return "medium"
    return "high"