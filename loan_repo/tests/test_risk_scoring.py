import pytest

from loan_calc.models import Applicant
from loan_calc.risk_scoring import risk_bucket, score_applicant


def test_score_is_high_for_strong_applicant(strong_applicant: Applicant) -> None:
    assert score_applicant(strong_applicant) >= 75


def test_score_is_low_for_weak_applicant(weak_applicant: Applicant) -> None:
    assert score_applicant(weak_applicant) < 50


def test_score_handles_invalid_income() -> None:
    applicant = Applicant("invalid", 30, 0, 100, 700, 24, "employee", 100000, 240)
    assert score_applicant(applicant) < 100


@pytest.mark.parametrize(
    ("score", "expected"),
    [(100, "low"), (75, "low"), (50, "medium"), (49, "high"), (0, "high")],
)
def test_risk_bucket(score: int, expected: str) -> None:
    assert risk_bucket(score) == expected


def test_score_is_clamped_at_zero() -> None:
    applicant = Applicant("zero", 30, 1000, 3000, 200, 0, "employee", 100000, 240)
    assert score_applicant(applicant) == 0


def test_score_is_clamped_at_one_hundred() -> None:
    applicant = Applicant("max", 30, 10000, 0, 900, 240, "employee", 100000, 240)
    assert score_applicant(applicant) == 100