from django.conf import settings
from django.db import models
from django.utils import timezone


class IssueReport(models.Model):
    class Category(models.TextChoices):
        DONATION = "donation", "Food Donation"
        DELIVERY = "delivery", "Pickup / Delivery"
        ACCOUNT = "account", "Account or Verification"
        TECHNICAL = "technical", "Technical Problem"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_REVIEW = "in_review", "In Review"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Dismissed"

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="issues"
    )
    related_donation = models.ForeignKey(
        "donations.FoodDonation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issues",
    )
    subject = models.CharField(max_length=150)
    category = models.CharField(
        max_length=20, choices=Category.choices, default=Category.OTHER
    )
    description = models.TextField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    admin_notes = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_issues",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def status_css(self) -> str:
        return {
            self.Status.OPEN: "warning",
            self.Status.IN_REVIEW: "info",
            self.Status.RESOLVED: "success",
            self.Status.DISMISSED: "secondary",
        }.get(self.status, "secondary")

    def __str__(self) -> str:
        return self.subject
