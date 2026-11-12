"""Donation timeline and audit helpers."""

from __future__ import annotations

from django.utils import timezone

from .models import AuditLog, DonationTracking


STATUS_TITLES = {
    "available": "Donation created",
    "requested": "NGO requested food",
    "accepted": "Donor accepted request",
    "assigned": "Volunteer assigned",
    "picked_up": "Food picked up",
    "delivered": "Food delivered",
    "completed": "Donation completed",
    "expired": "Donation expired",
    "cancelled": "Donation cancelled",
}

JOURNEY_STEPS = [
    {"key": "available", "label": "Donation Created", "icon": "fa-plus"},
    {"key": "requested", "label": "NGO Requested", "icon": "fa-hand-holding-heart"},
    {"key": "accepted", "label": "Donor Accepted", "icon": "fa-circle-check"},
    {"key": "assigned", "label": "Volunteer Assigned", "icon": "fa-user-group"},
    {"key": "picked_up", "label": "Food Picked Up", "icon": "fa-box"},
    {"key": "delivered", "label": "Food Delivered", "icon": "fa-truck-fast"},
    {"key": "completed", "label": "Completed", "icon": "fa-flag-checkered"},
]


def record_event(donation, status: str, title: str = "", description: str = "", actor=None):
    return DonationTracking.objects.create(
        donation=donation,
        status=status,
        title=title or STATUS_TITLES.get(status, status.replace("_", " ").title()),
        description=description,
        actor=actor,
    )


def log_audit(
    *,
    actor=None,
    action: str,
    description: str,
    obj=None,
    request=None,
    ip_address: str | None = None,
):
    if ip_address is None and request is not None:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        ip_address = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")
    model_name = ""
    object_id = ""
    if obj is not None:
        model_name = obj.__class__.__name__
        object_id = str(getattr(obj, "pk", ""))
    return AuditLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action[:60],
        model_name=model_name,
        object_id=object_id,
        description=description,
        ip_address=ip_address or None,
    )


def build_journey(donation):
    """Return progress-tracker steps enriched with actual event timestamps."""
    events = {event.status: event for event in donation.tracking_events.all()}
    status_order = {step["key"]: index for index, step in enumerate(JOURNEY_STEPS)}

    current_index = status_order.get(donation.status)
    if donation.status in {"expired", "cancelled"}:
        # For terminal exceptions, highlight the furthest real workflow event.
        completed_indexes = [status_order[event.status] for event in events.values() if event.status in status_order]
        current_index = max(completed_indexes) if completed_indexes else 0

    steps = []
    for index, step in enumerate(JOURNEY_STEPS):
        event = events.get(step["key"])
        steps.append(
            {
                **step,
                "index": index,
                "done": current_index is not None and index < current_index,
                "current": current_index is not None and index == current_index,
                "event": event,
            }
        )
    return steps


def serialize_status(donation):
    return {
        "id": donation.pk,
        "status": donation.status,
        "status_label": donation.get_status_display(),
        "status_css": donation.status_css,
        "is_expired": donation.is_expired,
        "expires_at": donation.expires_at.isoformat(),
        "updated_at": donation.updated_at.isoformat(),
        "server_time": timezone.now().isoformat(),
    }
