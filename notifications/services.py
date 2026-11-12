"""Central helper for creating in-app notifications."""

from __future__ import annotations

from django.contrib.auth import get_user_model

from .models import Notification

User = get_user_model()


def notify(
    user,
    title: str,
    message: str,
    *,
    level: str = Notification.Level.INFO,
    url: str = "",
    event_key: str | None = None,
):
    """Create a notification, optionally de-duplicated by an event key."""
    if user is None or not getattr(user, "pk", None):
        return None

    if event_key and Notification.objects.filter(event_key=event_key).exists():
        return None

    return Notification.objects.create(
        user=user,
        title=title[:150],
        message=message,
        level=level,
        url=url[:500],
        event_key=event_key,
    )


def notify_many(users, title: str, message: str, **kwargs):
    created = []
    seen = set()
    for user in users:
        if not user or user.pk in seen:
            continue
        seen.add(user.pk)
        note = notify(user, title, message, **kwargs)
        if note:
            created.append(note)
    return created
