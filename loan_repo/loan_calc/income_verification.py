from .models import Applicant


def verify_income(applicant: Applicant) -> bool:
    """Return whether income and employment history meet baseline requirements."""

    return applicant.monthly_income > 0 and applicant.employment_months >= 6


def annualized_income(applicant: Applicant) -> float:
    """Convert an applicant's monthly income to an annual amount."""

    return applicant.monthly_income * 12