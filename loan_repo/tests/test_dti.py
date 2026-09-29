import pytest

from loan_calc.dti import calculate_dti, dti_band


def test_calculate_dti_returns_decimal_ratio() -> None:
    assert calculate_dti(1750, 5000) == pytest.approx(0.35)


def test_calculate_dti_rejects_nonpositive_income() -> None:
    with pytest.raises(ValueError):
        calculate_dti(100, 0)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.20, "low"), (0.36, "moderate"), (0.43, "moderate"), (0.44, "high")],
)
def test_dti_band(value: float, expected: str) -> None:
    assert dti_band(value) == expected