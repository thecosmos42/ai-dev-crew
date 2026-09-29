from loan_calc.eligibility import evaluate
from loan_calc.models import Applicant


def test_evaluate_approves_strong_applicant(strong_applicant: Applicant) -> None:
    decision = evaluate(strong_applicant)
    assert decision.approved
    assert decision.rate is not None
    assert decision.reasons == []


def test_evaluate_declines_underage(weak_applicant: Applicant) -> None:
    decision = evaluate(weak_applicant)
    assert not decision.approved
    assert "underage" in decision.reasons


def test_evaluate_declines_low_credit() -> None:
    applicant = Applicant("credit", 30, 5000, 1000, 579, 24, "employee", 100000, 240)
    decision = evaluate(applicant)
    assert "credit_score_below_minimum" in decision.reasons


def test_evaluate_declines_high_dti() -> None:
    applicant = Applicant("dti", 30, 5000, 2200, 760, 24, "employee", 100000, 240)
    decision = evaluate(applicant)
    assert "dti_above_maximum" in decision.reasons


def test_evaluate_declines_invalid_income() -> None:
    applicant = Applicant("income", 30, 0, 0, 760, 24, "employee", 100000, 240)
    decision = evaluate(applicant)
    assert "invalid_income" in decision.reasons
    assert "income_not_verified" in decision.reasons


def test_evaluate_declines_low_risk() -> None:
    applicant = Applicant("risk", 30, 5000, 2500, 500, 0, "employee", 100000, 240)
    decision = evaluate(applicant)
    assert "risk_score_below_minimum" in decision.reasons