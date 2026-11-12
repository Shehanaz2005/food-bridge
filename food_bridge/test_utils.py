"""Shared object factories for Food Bridge tests."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from accounts.models import DonorProfile, NGOProfile, User, VolunteerProfile
from donations.models import DonationRequest, FoodDonation
from volunteers.models import PickupAssignment

DEFAULT_PASSWORD = "TestPass123!"


def make_user(username, role=User.Role.DONOR, password=DEFAULT_PASSWORD, **kwargs):
    fields = {
        "email": f"{username}@example.com",
        "first_name": kwargs.pop("first_name", username.replace("_", " ").title()),
        "last_name": kwargs.pop("last_name", ""),
        "city": kwargs.pop("city", "Mumbai"),
        "phone": kwargs.pop("phone", "+91 90000 00000"),
        "address": kwargs.pop("address", "10 Test Street, Mumbai"),
        "role": role,
        **kwargs,
    }
    user = User.objects.create_user(username=username, password=password, **fields)
    if role == User.Role.DONOR:
        DonorProfile.objects.get_or_create(
            user=user,
            defaults={
                "donor_type": DonorProfile.DonorType.INDIVIDUAL,
                "organization_name": fields["first_name"],
            },
        )
    elif role == User.Role.NGO:
        # The post_save signal already creates a profile, so update it in place
        # to ensure factory-created NGOs start verified. Creating the profile
        # from the signal also caches it on the user instance, so clear that
        # cache or later reads would see the unverified copy.
        NGOProfile.objects.update_or_create(
            user=user,
            defaults={
                "organization_name": fields["first_name"],
                "service_area": fields["city"],
                "verified": True,
                "verified_at": timezone.now(),
            },
        )
        user._state.fields_cache.pop("ngo_profile", None)
    elif role == User.Role.VOLUNTEER:
        VolunteerProfile.objects.get_or_create(
            user=user,
            defaults={"service_area": fields["city"], "is_available": True},
        )
    return user


def make_admin(username="admin_user"):
    return make_user(username, role=User.Role.ADMIN, is_staff=True, is_superuser=True)


def make_donation(donor, *, status=FoodDonation.Status.AVAILABLE, **kwargs):
    now = timezone.now()
    fields = {
        "food_name": "Test Biryani",
        "category": "cooked_meal",
        "description": "Freshly prepared test food.",
        "quantity": 20,
        "unit": "meals",
        "prepared_at": now - timedelta(hours=1),
        "expires_at": now + timedelta(hours=8),
        "pickup_address": "10 Test Street",
        "pickup_city": donor.city or "Mumbai",
        "pickup_contact_name": donor.display_name,
        "pickup_contact_phone": "+91 90000 00000",
        "handling_instructions": "Keep covered and refrigerated.",
        "status": status,
    }
    fields.update(kwargs)
    return FoodDonation.objects.create(donor=donor, **fields)


def make_request(donation, ngo, *, status=DonationRequest.Status.PENDING, **kwargs):
    fields = {
        "donation": donation,
        "ngo": ngo,
        "quantity": kwargs.pop("quantity", donation.quantity),
        "message": kwargs.pop("message", "We can collect and distribute this food."),
        "status": status,
    }
    fields.update(kwargs)
    return DonationRequest.objects.create(**fields)


def make_assignment(
    donation,
    volunteer,
    *,
    status=PickupAssignment.Status.OFFERED,
    assigned_by=None,
    **kwargs,
):
    fields = {
        "donation": donation,
        "volunteer": volunteer,
        "status": status,
        "assigned_by": assigned_by,
        "notes": kwargs.pop("notes", "Collect from the service entrance."),
    }
    fields.update(kwargs)
    return PickupAssignment.objects.create(**fields)
