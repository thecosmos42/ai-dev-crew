import pytest

from loan_calc.models import Applicant


@pytest.fixture
def strong_applicant() -> Applicant:
    return Applicant("strong", 30, 6000, 1500, 760, 36, "employee", 250000, 360)


@pytest.fixture
def weak_applicant() -> Applicant:
    return Applicant("weak", 17, 3000, 1800, 540, 3, "employee", 100000, 240)