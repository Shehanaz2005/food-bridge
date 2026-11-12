from django.conf import settings
from django.db import models
from django.utils import timezone

from donations.models import FoodDonation


class DonationTracking(models.Model):
    donation = models.ForeignKey(
        FoodDonation, on_delete=models.CASCADE, related_name="tracking_events"
    )
    status = models.CharField(max_length=20, choices=FoodDonation.Status.choices)
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tracking_actions",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self) -> str:
        return f"{self.donation.food_name}: {self.title}"


class AuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_actions",
    )
    action = models.CharField(max_length=60, db_index=True)
    model_name = models.CharField(max_length=80, blank=True)
    object_id = models.CharField(max_length=40, blank=True)
    description = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "audit log entry"
        verbose_name_plural = "audit log entries"

    def __str__(self) -> str:
        return f"{self.action} — {self.created_at:%d %b %Y %H:%M}"
