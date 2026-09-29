import pytest

from loan_calc.models import Applicant
from loan_calc.rates import RATE_TIERS, pick_rate


@pytest.mark.parametrize(
    ("score", "expected"),
    [(760, 0.060), (700, 0.070), (650, 0.085), (590, 0.105), (500, 0.105)],
)
def test_pick_rate_uses_credit_tiers(score: int, expected: float) -> None:
    applicant = Applicant("rate", 30, 5000, 1000, score, 24, "employee", 100000, 240)
    assert pick_rate(applicant) == pytest.approx(expected)


def test_pick_rate_adds_high_dti_surcharge() -> None:
    applicant = Applicant("rate", 30, 5000, 1800, 760, 24, "employee", 100000, 240)
    assert pick_rate(applicant) == pytest.approx(0.065)


def test_rate_tiers_are_ordered_policy_points() -> None:
    assert RATE_TIERS[740] < RATE_TIERS[680] < RATE_TIERS[620] < RATE_TIERS[580]