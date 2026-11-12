"""Food expiry monitoring and notification services."""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification
from notifications.services import notify
from tracking.services import record_event

from .models import DonationRequest, FoodDonation


def expire_donation(donation_id, *, actor=None) -> bool:
    """Safely expire a donation before pickup and notify everyone affected."""
    from .workflow import transition_donation

    with transaction.atomic():
        donation = FoodDonation.objects.select_for_update().get(pk=donation_id)
        if donation.status in {
            FoodDonation.Status.COMPLETED,
            FoodDonation.Status.CANCELLED,
            FoodDonation.Status.EXPIRED,
            FoodDonation.Status.PICKED_UP,
            FoodDonation.Status.DELIVERED,
        }:
            return False

        affected_ngos = []
        active_requests = donation.requests.filter(
            status__in=[DonationRequest.Status.PENDING, DonationRequest.Status.ACCEPTED]
        ).select_related("ngo")
        for request in active_requests:
            request.status = DonationRequest.Status.EXPIRED
            request.donor_note = "The food expired before it could be collected."
            request.responded_at = timezone.now()
            request.save(update_fields=["status", "donor_note", "responded_at", "updated_at"])
            affected_ngos.append(request.ngo)

        assignment = getattr(donation, "assignment", None)
        if assignment and assignment.status in {
            assignment.Status.OFFERED,
            assignment.Status.ACCEPTED,
        }:
            assignment.status = assignment.Status.CANCELLED
            assignment.save(update_fields=["status", "updated_at"])
            notify(
                assignment.volunteer,
                "Pickup cancelled — food expired",
                f"The donation “{donation.food_name}” expired before pickup. Do not collect it.",
                level=Notification.Level.DANGER,
                url=reverse("volunteers:assignments"),
                event_key=f"expired-assignment:{donation.pk}:{assignment.volunteer_id}",
            )

        transition_donation(
            donation,
            FoodDonation.Status.EXPIRED,
            actor=actor,
            title="Donation expired",
            description="The safe consumption window passed before pickup.",
        )

        notify(
            donation.donor,
            "Donation expired",
            f"“{donation.food_name}” expired before pickup and is no longer available. "
            "Food Bridge has removed it from the marketplace for safety.",
            level=Notification.Level.DANGER,
            url=reverse("donations:detail", kwargs={"pk": donation.pk}),
            event_key=f"expired-donor:{donation.pk}",
        )
        for ngo in affected_ngos:
            notify(
                ngo,
                "Request closed — food expired",
                f"The donation “{donation.food_name}” expired before pickup. "
                "It has been removed from the marketplace.",
                level=Notification.Level.WARNING,
                url=reverse("donations:requests"),
                event_key=f"expired-ngo:{donation.pk}:{ngo.pk}",
            )
        return True


def expire_overdue_donations() -> int:
    """Lazy safety net: expire any active, overdue donations right now."""
    ids = list(
        FoodDonation.objects.overdue()
        .exclude(status__in=[FoodDonation.Status.PICKED_UP, FoodDonation.Status.DELIVERED])
        .values_list("pk", flat=True)
    )
    expired = 0
    for donation_id in ids:
        if expire_donation(donation_id):
            expired += 1
    return expired


def send_expiry_warnings(hours: int = 6) -> int:
    """Notify donors, NGOs, and volunteers about food expiring soon."""
    moment = timezone.now() + timedelta(hours=hours)
    donations = (
        FoodDonation.objects.active()
        .filter(expires_at__gt=timezone.now(), expires_at__lte=moment)
        .select_related("donor")
    )
    warned = 0
    for donation in donations:
        recipients = {donation.donor_id: donation.donor}
        for request in donation.requests.filter(
            status__in=[DonationRequest.Status.PENDING, DonationRequest.Status.ACCEPTED]
        ).select_related("ngo"):
            recipients[request.ngo_id] = request.ngo
        assignment = getattr(donation, "assignment", None)
        if assignment and assignment.status in {
            assignment.Status.OFFERED,
            assignment.Status.ACCEPTED,
        }:
            recipients[assignment.volunteer_id] = assignment.volunteer

        for user in recipients.values():
            notify(
                user,
                "Food is approaching expiry",
                f"“{donation.food_name}” expires within {hours} hours. "
                "Please coordinate the pickup quickly to avoid waste.",
                level=Notification.Level.WARNING,
                url=reverse("donations:detail", kwargs={"pk": donation.pk}),
                event_key=f"expiry-warning:{donation.pk}:{user.pk}",
            )
        warned += 1
    return warned
