from loan_calc.income_verification import annualized_income, verify_income
from loan_calc.models import Applicant


def test_verify_income_accepts_sufficient_history(strong_applicant: Applicant) -> None:
    assert verify_income(strong_applicant)


def test_verify_income_rejects_short_history(weak_applicant: Applicant) -> None:
    assert not verify_income(weak_applicant)


def test_verify_income_rejects_nonpositive_income() -> None:
    applicant = Applicant("zero", 30, 0, 0, 700, 12, "employee", 100000, 240)
    assert not verify_income(applicant)


def test_annualized_income(strong_applicant: Applicant) -> None:
    assert annualized_income(strong_applicant) == 72000