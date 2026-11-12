"""Donation workflow services.

Every state change passes through this module so invalid transitions are
rejected consistently and notifications/timeline events are always recorded.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification
from notifications.services import notify, notify_many
from tracking.services import record_event

from .models import DonationRequest, FoodDonation

ALLOWED_TRANSITIONS = {
    FoodDonation.Status.AVAILABLE: {
        FoodDonation.Status.REQUESTED,
        FoodDonation.Status.CANCELLED,
        FoodDonation.Status.EXPIRED,
    },
    FoodDonation.Status.REQUESTED: {
        FoodDonation.Status.ACCEPTED,
        FoodDonation.Status.AVAILABLE,
        FoodDonation.Status.CANCELLED,
        FoodDonation.Status.EXPIRED,
    },
    FoodDonation.Status.ACCEPTED: {
        FoodDonation.Status.ASSIGNED,
        FoodDonation.Status.CANCELLED,
        FoodDonation.Status.EXPIRED,
    },
    FoodDonation.Status.ASSIGNED: {
        FoodDonation.Status.PICKED_UP,
        FoodDonation.Status.ACCEPTED,
        FoodDonation.Status.CANCELLED,
        FoodDonation.Status.EXPIRED,
    },
    FoodDonation.Status.PICKED_UP: {FoodDonation.Status.DELIVERED},
    FoodDonation.Status.DELIVERED: {FoodDonation.Status.COMPLETED},
    FoodDonation.Status.COMPLETED: set(),
    FoodDonation.Status.EXPIRED: set(),
    FoodDonation.Status.CANCELLED: set(),
}


def donation_url(donation) -> str:
    return reverse("donations:detail", kwargs={"pk": donation.pk})


def assignment_url(assignment) -> str:
    return reverse("volunteers:assignment_detail", kwargs={"pk": assignment.pk})


def transition_donation(
    donation: FoodDonation,
    new_status: str,
    *,
    actor=None,
    title: str = "",
    description: str = "",
    save: bool = True,
) -> FoodDonation:
    allowed = ALLOWED_TRANSITIONS.get(donation.status, set())
    if new_status not in allowed:
        raise ValidationError(
            f"Invalid workflow transition: {donation.get_status_display()} → "
            f"{dict(FoodDonation.Status.choices).get(new_status, new_status)}."
        )

    if new_status == FoodDonation.Status.PICKED_UP and donation.is_expired:
        raise ValidationError("Expired food cannot be picked up or distributed.")

    donation.status = new_status
    if save:
        donation.save(update_fields=["status", "updated_at"])
        record_event(donation, new_status, title=title, description=description, actor=actor)
    return donation


def create_donation_request(donation_id, ngo, quantity, message=""):
    try:
        requested_quantity = Decimal(str(quantity))
    except (InvalidOperation, TypeError):
        raise ValidationError("Enter a valid quantity.")

    with transaction.atomic():
        donation = FoodDonation.objects.select_for_update().get(pk=donation_id)
        profile = getattr(ngo, "ngo_profile", None)
        if profile is None or not profile.verified:
            raise ValidationError("Your NGO must be verified before requesting food.")
        if not donation.can_be_requested:
            raise ValidationError("This donation is expired or no longer available.")
        if requested_quantity <= 0:
            raise ValidationError("Requested quantity must be greater than zero.")
        if requested_quantity > donation.quantity:
            raise ValidationError("Requested quantity cannot exceed the donated quantity.")
        if DonationRequest.objects.filter(donation=donation, ngo=ngo).exists():
            raise ValidationError("You have already submitted a request for this donation.")

        if donation.status == FoodDonation.Status.AVAILABLE:
            transition_donation(
                donation,
                FoodDonation.Status.REQUESTED,
                actor=ngo,
                description=f"{ngo.display_name} requested {requested_quantity} {donation.get_unit_display()}.",
            )

        request = DonationRequest.objects.create(
            donation=donation,
            ngo=ngo,
            quantity=requested_quantity,
            message=message.strip(),
        )

        notify(
            donation.donor,
            "New donation request",
            f"{ngo.display_name} requested {request.quantity} {donation.get_unit_display()} of "
            f"{donation.food_name}.",
            level=Notification.Level.INFO,
            url=donation_url(donation),
        )
        return request


def accept_request(request_id, actor):
    with transaction.atomic():
        request = DonationRequest.objects.select_related("donation", "ngo").get(pk=request_id)
        donation = FoodDonation.objects.select_for_update().get(pk=request.donation_id)
        request = DonationRequest.objects.select_for_update().get(pk=request_id)

        if request.status != DonationRequest.Status.PENDING:
            raise ValidationError("Only pending requests can be accepted.")
        if donation.donor_id != getattr(actor, "pk", None) and not getattr(actor, "is_staff", False):
            raise ValidationError("Only the donor can accept this request.")
        if donation.is_expired:
            raise ValidationError("This donation has expired and cannot be accepted.")
        if donation.status not in {
            FoodDonation.Status.AVAILABLE,
            FoodDonation.Status.REQUESTED,
        }:
            raise ValidationError("This donation is no longer open for requests.")

        if donation.status == FoodDonation.Status.AVAILABLE:
            transition_donation(donation, FoodDonation.Status.REQUESTED, actor=actor)

        request.status = DonationRequest.Status.ACCEPTED
        request.responded_at = timezone.now()
        request.save(update_fields=["status", "responded_at", "updated_at"])

        rejected_ngos = []
        other_pending = donation.requests.filter(status=DonationRequest.Status.PENDING).exclude(pk=request.pk)
        for other in other_pending:
            other.status = DonationRequest.Status.REJECTED
            other.donor_note = "The donor allocated this donation to another NGO."
            other.responded_at = timezone.now()
            other.save(update_fields=["status", "donor_note", "responded_at", "updated_at"])
            rejected_ngos.append(other.ngo)

        transition_donation(
            donation,
            FoodDonation.Status.ACCEPTED,
            actor=actor,
            title="Donor accepted request",
            description=f"Food allocated to {request.ngo.display_name}.",
        )

        notify(
            request.ngo,
            "Your food request was accepted",
            f"{donation.donor.display_name} accepted your request for {donation.food_name}. "
            "A volunteer will be assigned for pickup.",
            level=Notification.Level.SUCCESS,
            url=donation_url(donation),
        )
        for ngo in rejected_ngos:
            notify(
                ngo,
                "Donation allocated to another NGO",
                f"The donation “{donation.food_name}” has been allocated to another organisation. "
                "Browse other available food nearby.",
                level=Notification.Level.INFO,
                url=reverse("donations:browse"),
            )
        return request


def reject_request(request_id, actor, note=""):
    with transaction.atomic():
        request = DonationRequest.objects.select_related("donation", "ngo").get(pk=request_id)
        donation = FoodDonation.objects.select_for_update().get(pk=request.donation_id)
        request = DonationRequest.objects.select_for_update().get(pk=request_id)

        if request.status != DonationRequest.Status.PENDING:
            raise ValidationError("Only pending requests can be rejected.")
        if donation.donor_id != getattr(actor, "pk", None) and not getattr(actor, "is_staff", False):
            raise ValidationError("Only the donor can reject this request.")

        request.status = DonationRequest.Status.REJECTED
        request.donor_note = note.strip() or "The donor is unable to fulfil this request."
        request.responded_at = timezone.now()
        request.save(update_fields=["status", "donor_note", "responded_at", "updated_at"])

        if not donation.requests.filter(status=DonationRequest.Status.PENDING).exists():
            if donation.status == FoodDonation.Status.REQUESTED:
                transition_donation(
                    donation,
                    FoodDonation.Status.AVAILABLE,
                    actor=actor,
                    title="Donation available again",
                    description="No pending NGO requests remain.",
                )

        notify(
            request.ngo,
            "Your food request was declined",
            f"{donation.donor.display_name} could not fulfil your request for {donation.food_name}. "
            f"Note: {request.donor_note}",
            level=Notification.Level.WARNING,
            url=donation_url(donation),
        )
        return request


def cancel_request_by_ngo(request_id, actor):
    with transaction.atomic():
        request = DonationRequest.objects.select_related("donation", "ngo").get(pk=request_id)
        donation = FoodDonation.objects.select_for_update().get(pk=request.donation_id)
        request = DonationRequest.objects.select_for_update().get(pk=request_id)

        if request.ngo_id != actor.pk:
            raise ValidationError("You can only cancel your own request.")
        if request.status != DonationRequest.Status.PENDING:
            raise ValidationError("Only pending requests can be cancelled.")

        request.status = DonationRequest.Status.CANCELLED
        request.responded_at = timezone.now()
        request.save(update_fields=["status", "responded_at", "updated_at"])

        if not donation.requests.filter(status=DonationRequest.Status.PENDING).exists():
            if donation.status == FoodDonation.Status.REQUESTED:
                transition_donation(
                    donation,
                    FoodDonation.Status.AVAILABLE,
                    actor=actor,
                    title="Donation available again",
                    description="The NGO cancelled its request.",
                )

        notify(
            donation.donor,
            "NGO request cancelled",
            f"{request.ngo.display_name} cancelled its request for {donation.food_name}.",
            level=Notification.Level.INFO,
            url=donation_url(donation),
        )
        return request


def cancel_donation(donation_id, actor, reason=""):
    with transaction.atomic():
        donation = FoodDonation.objects.select_for_update().get(pk=donation_id)
        if donation.donor_id != getattr(actor, "pk", None) and not getattr(actor, "is_staff", False):
            raise ValidationError("You do not have permission to cancel this donation.")
        if donation.status not in {
            FoodDonation.Status.AVAILABLE,
            FoodDonation.Status.REQUESTED,
            FoodDonation.Status.ACCEPTED,
            FoodDonation.Status.ASSIGNED,
        }:
            raise ValidationError("This donation can no longer be cancelled.")

        affected_users = []
        pending_requests = donation.requests.filter(status=DonationRequest.Status.PENDING)
        for request in pending_requests:
            request.status = DonationRequest.Status.CANCELLED
            request.donor_note = "The donor cancelled this donation."
            request.responded_at = timezone.now()
            request.save(update_fields=["status", "donor_note", "responded_at", "updated_at"])
            affected_users.append(request.ngo)

        accepted = donation.requests.filter(status=DonationRequest.Status.ACCEPTED).first()
        if accepted:
            accepted.status = DonationRequest.Status.CANCELLED
            accepted.donor_note = "The donor cancelled this donation before pickup."
            accepted.responded_at = timezone.now()
            accepted.save(update_fields=["status", "donor_note", "responded_at", "updated_at"])
            affected_users.append(accepted.ngo)

        assignment = getattr(donation, "assignment", None)
        if assignment and assignment.is_active:
            assignment.status = assignment.Status.CANCELLED
            assignment.save(update_fields=["status", "updated_at"])
            notify(
                assignment.volunteer,
                "Pickup assignment cancelled",
                f"The donation “{donation.food_name}” was cancelled by the donor.",
                level=Notification.Level.WARNING,
                url=reverse("volunteers:assignments"),
            )

        transition_donation(
            donation,
            FoodDonation.Status.CANCELLED,
            actor=actor,
            title="Donation cancelled",
            description=reason.strip() or "The donor cancelled this donation.",
        )
        donation.cancelled_reason = (reason.strip() or "Cancelled by donor")[:255]
        donation.save(update_fields=["cancelled_reason", "updated_at"])

        notify_many(
            affected_users,
            "Donation cancelled",
            f"{donation.donor.display_name} cancelled the donation “{donation.food_name}”.",
            level=Notification.Level.WARNING,
            url=donation_url(donation),
        )
        return donation


def assign_volunteer(donation_id, volunteer, actor, notes=""):
    from accounts.models import User
    from volunteers.models import PickupAssignment

    with transaction.atomic():
        donation = FoodDonation.objects.select_for_update().get(pk=donation_id)
        if donation.status not in {
            FoodDonation.Status.ACCEPTED,
            FoodDonation.Status.ASSIGNED,
        }:
            raise ValidationError("A volunteer can only be assigned after a donor accepts a request.")
        if donation.is_expired:
            raise ValidationError("Expired food cannot be assigned for pickup.")
        if not donation.requests.filter(status=DonationRequest.Status.ACCEPTED).exists():
            raise ValidationError("This donation has no accepted NGO request.")
        if volunteer.role != User.Role.VOLUNTEER:
            raise ValidationError("Select a volunteer account.")
        profile = getattr(volunteer, "volunteer_profile", None)
        if profile is None or not profile.is_available:
            raise ValidationError("This volunteer is currently unavailable.")

        existing = PickupAssignment.objects.select_for_update().filter(donation=donation).first()
        if existing and existing.is_active:
            raise ValidationError("This donation already has an active pickup assignment.")

        if existing:
            existing.volunteer = volunteer
            existing.assigned_by = actor
            existing.status = PickupAssignment.Status.OFFERED
            existing.notes = notes.strip()
            existing.accepted_at = None
            existing.picked_up_at = None
            existing.delivered_at = None
            existing.completed_at = None
            existing.save()
            assignment = existing
        else:
            assignment = PickupAssignment.objects.create(
                donation=donation,
                volunteer=volunteer,
                assigned_by=actor,
                notes=notes.strip(),
            )

        if donation.status == FoodDonation.Status.ACCEPTED:
            transition_donation(
                donation,
                FoodDonation.Status.ASSIGNED,
                actor=actor,
                title="Volunteer assigned",
                description=f"{volunteer.display_name} was assigned to collect the food.",
            )

        notify(
            volunteer,
            "New pickup assignment",
            f"You have been assigned to collect “{donation.food_name}” from "
            f"{donation.pickup_city}. Please accept or decline the assignment.",
            level=Notification.Level.INFO,
            url=assignment_url(assignment),
        )
        notify(
            donation.donor,
            "Volunteer assigned for pickup",
            f"{volunteer.display_name} will collect your donation “{donation.food_name}”.",
            level=Notification.Level.INFO,
            url=donation_url(donation),
        )
        ngo = donation.recipient_ngo
        if ngo:
            notify(
                ngo,
                "Volunteer assigned for your food",
                f"{volunteer.display_name} will deliver “{donation.food_name}” to your organisation.",
                level=Notification.Level.INFO,
                url=donation_url(donation),
            )
        return assignment


def volunteer_accept_assignment(assignment_id, actor):
    from volunteers.models import PickupAssignment

    with transaction.atomic():
        assignment = PickupAssignment.objects.select_related("donation").get(pk=assignment_id)
        donation = FoodDonation.objects.select_for_update().get(pk=assignment.donation_id)
        assignment = PickupAssignment.objects.select_for_update().get(pk=assignment_id)

        if assignment.volunteer_id != actor.pk:
            raise ValidationError("This assignment is not yours.")
        if assignment.status != PickupAssignment.Status.OFFERED:
            raise ValidationError("This assignment can no longer be accepted.")
        if donation.status != FoodDonation.Status.ASSIGNED:
            raise ValidationError("This donation is not awaiting volunteer pickup.")
        if donation.is_expired:
            raise ValidationError("The food has expired and cannot be collected.")

        assignment.status = PickupAssignment.Status.ACCEPTED
        assignment.accepted_at = timezone.now()
        assignment.save(update_fields=["status", "accepted_at", "updated_at"])
        record_event(
            donation,
            FoodDonation.Status.ASSIGNED,
            title="Volunteer accepted pickup",
            description=f"{actor.display_name} accepted the pickup assignment.",
            actor=actor,
        )

        if donation.donor_id:
            notify(
                donation.donor,
                "Volunteer accepted your pickup",
                f"{actor.display_name} accepted the assignment for “{donation.food_name}”.",
                level=Notification.Level.SUCCESS,
                url=donation_url(donation),
            )
        ngo = donation.recipient_ngo
        if ngo:
            notify(
                ngo,
                "Pickup confirmed by volunteer",
                f"{actor.display_name} will deliver “{donation.food_name}” to you.",
                level=Notification.Level.INFO,
                url=donation_url(donation),
            )
        return assignment


def volunteer_decline_assignment(assignment_id, actor, note=""):
    from volunteers.models import PickupAssignment

    with transaction.atomic():
        assignment = PickupAssignment.objects.select_related("donation", "assigned_by").get(
            pk=assignment_id
        )
        donation = FoodDonation.objects.select_for_update().get(pk=assignment.donation_id)
        assignment = PickupAssignment.objects.select_for_update().get(pk=assignment_id)

        if assignment.volunteer_id != actor.pk:
            raise ValidationError("This assignment is not yours.")
        if assignment.status not in {
            PickupAssignment.Status.OFFERED,
            PickupAssignment.Status.ACCEPTED,
        }:
            raise ValidationError("This assignment can no longer be declined.")

        assignment.status = PickupAssignment.Status.DECLINED
        assignment.notes = (assignment.notes + "\n" + note.strip()).strip()
        assignment.save(update_fields=["status", "notes", "updated_at"])

        if donation.status == FoodDonation.Status.ASSIGNED:
            transition_donation(
                donation,
                FoodDonation.Status.ACCEPTED,
                actor=actor,
                title="Volunteer unavailable",
                description="The assignment was declined and awaits a new volunteer.",
            )

        notify(
            donation.donor,
            "Volunteer unavailable",
            f"The assigned volunteer declined the pickup for “{donation.food_name}”. "
            "The Food Bridge team will assign another volunteer.",
            level=Notification.Level.WARNING,
            url=donation_url(donation),
        )
        ngo = donation.recipient_ngo
        if ngo:
            notify(
                ngo,
                "Volunteer reassignment in progress",
                f"A new volunteer is being arranged for “{donation.food_name}”.",
                level=Notification.Level.WARNING,
                url=donation_url(donation),
            )
        if assignment.assigned_by:
            notify(
                assignment.assigned_by,
                "Volunteer declined an assignment",
                f"{actor.display_name} declined the pickup for “{donation.food_name}”. "
                "Please assign another volunteer.",
                level=Notification.Level.WARNING,
                url=reverse("admin_assign", kwargs={"donation_id": donation.pk}),
            )
        return assignment


def mark_picked_up(assignment_id, actor):
    from volunteers.models import PickupAssignment

    with transaction.atomic():
        assignment = PickupAssignment.objects.select_related("donation").get(pk=assignment_id)
        donation = FoodDonation.objects.select_for_update().get(pk=assignment.donation_id)
        assignment = PickupAssignment.objects.select_for_update().get(pk=assignment_id)

        if assignment.volunteer_id != actor.pk:
            raise ValidationError("This assignment is not yours.")
        if assignment.status != PickupAssignment.Status.ACCEPTED:
            raise ValidationError("Accept the assignment before marking it picked up.")
        if donation.status != FoodDonation.Status.ASSIGNED:
            raise ValidationError("This donation is not ready for pickup.")
        if donation.is_expired:
            raise ValidationError("Expired food must not be collected. Contact the Food Bridge team.")

        assignment.status = PickupAssignment.Status.PICKED_UP
        assignment.picked_up_at = timezone.now()
        assignment.save(update_fields=["status", "picked_up_at", "updated_at"])
        transition_donation(
            donation,
            FoodDonation.Status.PICKED_UP,
            actor=actor,
            description=f"Collected by {actor.display_name}.",
        )

        notify(
            donation.donor,
            "Food picked up",
            f"{actor.display_name} collected “{donation.food_name}” for delivery.",
            level=Notification.Level.SUCCESS,
            url=donation_url(donation),
        )
        ngo = donation.recipient_ngo
        if ngo:
            notify(
                ngo,
                "Your food is on the way",
                f"“{donation.food_name}” has been picked up and is on the way to your NGO.",
                level=Notification.Level.INFO,
                url=donation_url(donation),
            )
        return assignment


def mark_delivered(assignment_id, actor):
    from volunteers.models import PickupAssignment

    with transaction.atomic():
        assignment = PickupAssignment.objects.select_related("donation").get(pk=assignment_id)
        donation = FoodDonation.objects.select_for_update().get(pk=assignment.donation_id)
        assignment = PickupAssignment.objects.select_for_update().get(pk=assignment_id)

        if assignment.volunteer_id != actor.pk:
            raise ValidationError("This assignment is not yours.")
        if assignment.status != PickupAssignment.Status.PICKED_UP:
            raise ValidationError("Mark the food as picked up before recording delivery.")
        if donation.status != FoodDonation.Status.PICKED_UP:
            raise ValidationError("This donation cannot be marked delivered yet.")

        assignment.status = PickupAssignment.Status.DELIVERED
        assignment.delivered_at = timezone.now()
        assignment.save(update_fields=["status", "delivered_at", "updated_at"])
        transition_donation(
            donation,
            FoodDonation.Status.DELIVERED,
            actor=actor,
            description=f"Delivered to the recipient NGO by {actor.display_name}.",
        )

        notify(
            donation.donor,
            "Food delivered",
            f"“{donation.food_name}” was delivered to the NGO. Thank you for sharing!",
            level=Notification.Level.SUCCESS,
            url=donation_url(donation),
        )
        ngo = donation.recipient_ngo
        if ngo:
            notify(
                ngo,
                "Food delivered — please confirm receipt",
                f"“{donation.food_name}” was delivered. Confirm receipt to complete the donation.",
                level=Notification.Level.SUCCESS,
                url=donation_url(donation),
            )
        return assignment


def complete_donation(donation_id, actor):
    from volunteers.models import PickupAssignment

    with transaction.atomic():
        donation = FoodDonation.objects.select_for_update().get(pk=donation_id)
        if donation.status != FoodDonation.Status.DELIVERED:
            raise ValidationError("Only delivered donations can be completed.")
        accepted = donation.requests.filter(status=DonationRequest.Status.ACCEPTED).first()
        if not accepted:
            raise ValidationError("This donation has no accepted NGO request.")
        if accepted.ngo_id != actor.pk and not getattr(actor, "is_staff", False):
            raise ValidationError("Only the recipient NGO can confirm receipt.")

        transition_donation(
            donation,
            FoodDonation.Status.COMPLETED,
            actor=actor,
            description=f"Receipt confirmed by {actor.display_name}.",
        )
        donation.completed_at = timezone.now()
        donation.save(update_fields=["completed_at", "updated_at"])
        accepted.status = DonationRequest.Status.FULFILLED
        accepted.save(update_fields=["status", "updated_at"])

        assignment = PickupAssignment.objects.filter(donation=donation).first()
        if assignment:
            assignment.status = PickupAssignment.Status.COMPLETED
            assignment.completed_at = timezone.now()
            assignment.save(update_fields=["status", "completed_at", "updated_at"])

        notify(
            donation.donor,
            "Donation completed",
            f"“{donation.food_name}” reached {accepted.ngo.display_name} and the donation is complete.",
            level=Notification.Level.SUCCESS,
            url=donation_url(donation),
        )
        if assignment:
            notify(
                assignment.volunteer,
                "Delivery completed",
                f"Your delivery of “{donation.food_name}” is complete. Thank you for volunteering!",
                level=Notification.Level.SUCCESS,
                url=reverse("volunteers:assignment_detail", kwargs={"pk": assignment.pk}),
            )
        return donation
