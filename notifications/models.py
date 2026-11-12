from django.conf import settings
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    class Level(models.TextChoices):
        INFO = "info", "Information"
        SUCCESS = "success", "Success"
        WARNING = "warning", "Warning"
        DANGER = "danger", "Urgent"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    title = models.CharField(max_length=150)
    message = models.TextField()
    level = models.CharField(max_length=20, choices=Level.choices, default=Level.INFO)
    url = models.CharField(max_length=500, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    event_key = models.CharField(
        max_length=180,
        unique=True,
        null=True,
        blank=True,
        help_text="Optional idempotency key used to prevent duplicate alerts.",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "is_read"])]

    @property
    def icon(self) -> str:
        return {
            self.Level.INFO: "fa-circle-info",
            self.Level.SUCCESS: "fa-circle-check",
            self.Level.WARNING: "fa-triangle-exclamation",
            self.Level.DANGER: "fa-circle-exclamation",
        }.get(self.level, "fa-bell")

    def __str__(self) -> str:
        return f"{self.user.display_name}: {self.title}"
