from django.conf import settings
from django.db import models
from django.utils import timezone

from donations.models import FoodDonation


class PickupAssignment(models.Model):
    class Status(models.TextChoices):
        OFFERED = "offered", "Awaiting Volunteer Response"
        ACCEPTED = "accepted", "Accepted by Volunteer"
        DECLINED = "declined", "Declined"
        PICKED_UP = "picked_up", "Food Picked Up"
        DELIVERED = "delivered", "Food Delivered"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    donation = models.OneToOneField(
        FoodDonation, on_delete=models.CASCADE, related_name="assignment"
    )
    volunteer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="volunteer_assignments",
        limit_choices_to={"role": "volunteer"},
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignments_made",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OFFERED, db_index=True
    )
    notes = models.TextField(
        blank=True, help_text="Pickup or handling notes for the volunteer."
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    status__in=[
                        "offered",
                        "accepted",
                        "declined",
                        "picked_up",
                        "delivered",
                        "completed",
                        "cancelled",
                    ]
                ),
                name="valid_assignment_status",
            )
        ]

    @property
    def status_css(self) -> str:
        return {
            self.Status.OFFERED: "warning",
            self.Status.ACCEPTED: "info",
            self.Status.DECLINED: "secondary",
            self.Status.PICKED_UP: "primary",
            self.Status.DELIVERED: "info",
            self.Status.COMPLETED: "success",
            self.Status.CANCELLED: "secondary",
        }.get(self.status, "secondary")

    @property
    def is_active(self) -> bool:
        return self.status in {
            self.Status.OFFERED,
            self.Status.ACCEPTED,
            self.Status.PICKED_UP,
            self.Status.DELIVERED,
        }

    def __str__(self) -> str:
        return f"{self.donation.food_name} → {self.volunteer.display_name}"
