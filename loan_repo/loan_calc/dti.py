def calculate_dti(monthly_debt: float, monthly_income: float) -> float:
    """Return the back-end debt-to-income ratio as a decimal."""

    if monthly_income <= 0:
        raise ValueError("monthly income must be greater than zero")
    return monthly_debt / monthly_income


def dti_band(dti: float) -> str:
    """Classify a DTI ratio for display and risk explanations."""

    if dti < 0.36:
        return "low"
    if dti <= 0.43:
        return "moderate"
    return "high"