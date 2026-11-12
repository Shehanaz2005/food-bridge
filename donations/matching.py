"""Rule-based smart matching between available food and NGO requirements."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from .models import FoodDonation


@dataclass
class MatchResult:
    donation: FoodDonation
    score: int
    level: str
    level_css: str
    reasons: list[str]

    @property
    def is_high(self) -> bool:
        return self.level == "High Match"


def score_donation(donation: FoodDonation, ngo) -> MatchResult:
    """Score a donation from 0–100 using transparent, explainable rules."""
    profile = getattr(ngo, "ngo_profile", None)
    score = 0
    reasons: list[str] = []

    # 1. Category preference — up to 35 points.
    preferred = list(profile.preferred_categories or []) if profile else []
    if not preferred:
        score += 20
        reasons.append("Your NGO has no category preferences, so all food types are considered.")
    elif donation.category in preferred:
        score += 35
        reasons.append(f"Matches your preferred food category: {donation.get_category_display()}.")
    else:
        score += 5
        reasons.append("Food category is outside your usual preferences.")

    # 2. Location fit — up to 25 points.
    ngo_city = (ngo.city if ngo else "").strip().casefold()
    pickup_city = (donation.pickup_city or "").strip().casefold()
    service_area = (profile.service_area if profile else "").strip().casefold()
    if ngo_city and pickup_city and ngo_city == pickup_city:
        score += 25
        reasons.append(f"Pickup is in your city, {donation.pickup_city}.")
    elif service_area and pickup_city and pickup_city in service_area:
        score += 20
        reasons.append("Pickup is inside your NGO's service area.")
    else:
        score += 5
        reasons.append(f"Pickup is in {donation.pickup_city}, outside your primary area.")

    # 3. Quantity against the NGO's stated minimum — up to 25 points.
    minimum = profile.minimum_quantity if profile else 0
    if not minimum or minimum <= 0:
        score += 15
        reasons.append("No minimum quantity has been set for your NGO.")
    elif donation.unit == profile.minimum_unit:
        if donation.quantity >= minimum:
            score += 25
            reasons.append(f"Provides the quantity you need ({donation.quantity_display}).")
        else:
            ratio = max(0.0, min(1.0, float(donation.quantity / minimum)))
            partial = max(3, round(25 * ratio))
            score += partial
            reasons.append("Quantity is below your preferred minimum, but still usable.")
    else:
        score += 12
        reasons.append("Minimum quantity uses a different unit; compare quantities before requesting.")

    # 4. Expiry urgency — up to 15 points. Food that needs rescuing soon ranks higher.
    hours_left = (donation.expires_at - timezone.now()).total_seconds() / 3600
    if hours_left <= 24:
        score += 15
        reasons.append("Expires within 24 hours, so it needs a fast rescue.")
    elif hours_left <= 48:
        score += 11
        reasons.append("Expires within 2 days.")
    elif hours_left <= 72:
        score += 7
        reasons.append("Expires within 3 days.")
    else:
        score += 4
        reasons.append("Has a longer remaining shelf life.")

    score = max(0, min(100, score))
    if score >= 75:
        level, level_css = "High Match", "success"
    elif score >= 50:
        level, level_css = "Medium Match", "warning"
    else:
        level, level_css = "Low Match", "secondary"

    return MatchResult(donation, score, level, level_css, reasons)


def rank_donations_for_ngo(donations, ngo) -> list[MatchResult]:
    """Rank a queryset/list of donations for an NGO, highest match first."""
    results = [score_donation(donation, ngo) for donation in donations if not donation.is_expired]
    results.sort(key=lambda item: (-item.score, item.donation.expires_at))
    return results


def recommended_volunteers(donation, limit: int = 5):
    """Available volunteers, prioritising those based in the pickup city."""
    from accounts.models import VolunteerProfile

    queryset = (
        VolunteerProfile.objects.select_related("user")
        .filter(user__is_blocked=False, is_available=True)
        .order_by("user__first_name")
    )
    ranked = sorted(
        queryset,
        key=lambda profile: (
            0 if profile.user.city.strip().casefold() == donation.pickup_city.strip().casefold() else 1,
            profile.completed_count * -1,
        ),
    )
    return ranked[:limit]
