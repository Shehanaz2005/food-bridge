"""Object-level access rules for food donations."""

from django.contrib.auth import get_user_model

from .models import DonationRequest, FoodDonation

User = get_user_model()


def is_assigned_volunteer(user, donation) -> bool:
    return (
        user.is_authenticated
        and user.role == User.Role.VOLUNTEER
        and getattr(getattr(donation, "assignment", None), "volunteer_id", None) == user.pk
    )


def ngo_has_request(user, donation) -> bool:
    return (
        user.is_authenticated
        and user.role == User.Role.NGO
        and donation.requests.filter(ngo=user).exists()
    )


def can_view_donation(user, donation) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_staff:
        return True
    if donation.donor_id == user.pk:
        return True
    if is_assigned_volunteer(user, donation):
        return True
    if ngo_has_request(user, donation):
        return True
    if user.role == User.Role.NGO:
        profile = getattr(user, "ngo_profile", None)
        active_statuses = {
            FoodDonation.Status.AVAILABLE,
            FoodDonation.Status.REQUESTED,
            FoodDonation.Status.ACCEPTED,
            FoodDonation.Status.ASSIGNED,
            FoodDonation.Status.PICKED_UP,
            FoodDonation.Status.DELIVERED,
        }
        # Unverified NGOs may browse active listings so they can see what is
        # available; the workflow still blocks them from submitting requests.
        return bool(profile and donation.status in active_statuses)
    return False


def can_view_private_contact(user, donation) -> bool:
    """Pickup address/phone visible to the owner, admin, assigned volunteer, or
    the NGO whose request the donor accepted."""
    if not user.is_authenticated:
        return False
    if user.is_staff or donation.donor_id == user.pk:
        return True
    if is_assigned_volunteer(user, donation):
        return True
    if user.role == User.Role.NGO:
        return donation.requests.filter(
            ngo=user,
            status__in=[DonationRequest.Status.ACCEPTED, DonationRequest.Status.FULFILLED],
        ).exists()
    return False


def can_request_donation(user, donation) -> bool:
    if not user.is_authenticated or user.role != User.Role.NGO:
        return False
    profile = getattr(user, "ngo_profile", None)
    if not profile or not profile.verified:
        return False
    if not donation.can_be_requested:
        return False
    return not donation.requests.filter(ngo=user).exists()
