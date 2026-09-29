from .dti import calculate_dti
from .models import Applicant

RATE_TIERS = {
    740: 0.060,
    680: 0.070,
    620: 0.085,
    580: 0.105,
}


def pick_rate(applicant: Applicant) -> float:
    """Select a base rate and add a surcharge for higher DTI."""

    dti = calculate_dti(applicant.monthly_debt_payments, applicant.monthly_income)
    eligible_tier = max(
        (threshold for threshold in RATE_TIERS if applicant.credit_score >= threshold),
        default=min(RATE_TIERS),
    )
    rate = RATE_TIERS[eligible_tier]
    if dti >= 0.36:
        rate += 0.005
    return rate