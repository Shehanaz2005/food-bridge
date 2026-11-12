from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone

from accounts.validators import validate_image_file

from .constants import (
    CATEGORY_ICONS,
    FOOD_CATEGORY_CHOICES,
    FOOD_UNIT_CHOICES,
    FOOD_UNIT_SHORT_LABELS,
)


class FoodDonationQuerySet(models.QuerySet):
    def active(self):
        """Donations that can still move through the rescue workflow."""
        return self.filter(
            status__in=[
                FoodDonation.Status.AVAILABLE,
                FoodDonation.Status.REQUESTED,
                FoodDonation.Status.ACCEPTED,
                FoodDonation.Status.ASSIGNED,
                FoodDonation.Status.PICKED_UP,
                FoodDonation.Status.DELIVERED,
            ]
        )

    def available_for_request(self):
        return self.filter(
            status__in=[FoodDonation.Status.AVAILABLE, FoodDonation.Status.REQUESTED],
            expires_at__gt=timezone.now(),
        )

    def expiring_before(self, moment):
        return self.active().filter(expires_at__lte=moment, expires_at__gt=timezone.now())

    def overdue(self):
        return self.active().filter(expires_at__lte=timezone.now())


class FoodDonation(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        REQUESTED = "requested", "NGO Requested"
        ACCEPTED = "accepted", "Request Accepted"
        ASSIGNED = "assigned", "Volunteer Assigned"
        PICKED_UP = "picked_up", "Picked Up"
        DELIVERED = "delivered", "Delivered"
        COMPLETED = "completed", "Completed"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"

    donor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="donations",
        limit_choices_to={"role": "donor"},
    )
    food_name = models.CharField(max_length=150)
    category = models.CharField(max_length=30, choices=FOOD_CATEGORY_CHOICES)
    description = models.TextField(
        blank=True, help_text="Ingredients, packaging, or other useful details."
    )
    quantity = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.1"))],
    )
    unit = models.CharField(max_length=20, choices=FOOD_UNIT_CHOICES, default="kg")
    image = models.ImageField(
        upload_to="donations/%Y/%m/",
        blank=True,
        validators=[validate_image_file],
        help_text="JPG, PNG, or WebP up to 5 MB.",
    )
    prepared_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    pickup_address = models.TextField()
    pickup_city = models.CharField(max_length=100)
    pickup_contact_name = models.CharField(max_length=120)
    pickup_contact_phone = models.CharField(max_length=20)
    handling_instructions = models.TextField(
        blank=True,
        help_text="Storage, reheating, allergen, or packaging instructions.",
    )
    is_vegetarian = models.BooleanField(default=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.AVAILABLE, db_index=True
    )
    cancelled_reason = models.CharField(max_length=255, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = FoodDonationQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "expires_at"]),
            models.Index(fields=["category", "pickup_city"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="donation_quantity_positive"
            ),
            models.CheckConstraint(
                condition=Q(expires_at__gt=F("prepared_at")),
                name="donation_expiry_after_preparation",
            ),
        ]

    def clean(self):
        errors = {}
        if self.prepared_at and self.expires_at and self.expires_at <= self.prepared_at:
            errors["expires_at"] = "Best-before time must be after the preparation time."
        if self.expires_at and self.status == self.Status.AVAILABLE:
            if self.expires_at <= timezone.now():
                errors["expires_at"] = "Choose a best-before time in the future."
        if errors:
            raise ValidationError(errors)

    @property
    def category_icon(self) -> str:
        return CATEGORY_ICONS.get(self.category, "fa-utensils")

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now() or self.status == self.Status.EXPIRED

    @property
    def is_active(self) -> bool:
        return self.status in {
            self.Status.AVAILABLE,
            self.Status.REQUESTED,
            self.Status.ACCEPTED,
            self.Status.ASSIGNED,
            self.Status.PICKED_UP,
            self.Status.DELIVERED,
        }

    @property
    def can_be_requested(self) -> bool:
        return (
            self.status in {self.Status.AVAILABLE, self.Status.REQUESTED}
            and not self.is_expired
        )

    @property
    def time_remaining(self):
        return self.expires_at - timezone.now()

    @property
    def quantity_display(self) -> str:
        value = f"{self.quantity:.2f}".rstrip("0").rstrip(".")
        unit = FOOD_UNIT_SHORT_LABELS.get(self.unit, self.get_unit_display())
        return f"{value} {unit}"

    @property
    def pickup_location(self) -> str:
        return f"{self.pickup_address}, {self.pickup_city}"

    @property
    def maps_query(self) -> str:
        return f"{self.pickup_address}, {self.pickup_city}"

    @property
    def accepted_request(self):
        return self.requests.filter(
            status__in=[DonationRequest.Status.ACCEPTED, DonationRequest.Status.FULFILLED]
        ).first()

    @property
    def recipient_ngo(self):
        request = self.accepted_request
        return request.ngo if request else None

    @property
    def status_css(self) -> str:
        return {
            self.Status.AVAILABLE: "success",
            self.Status.REQUESTED: "warning",
            self.Status.ACCEPTED: "info",
            self.Status.ASSIGNED: "primary",
            self.Status.PICKED_UP: "primary",
            self.Status.DELIVERED: "info",
            self.Status.COMPLETED: "success",
            self.Status.EXPIRED: "danger",
            self.Status.CANCELLED: "secondary",
        }.get(self.status, "secondary")

    def get_absolute_url(self):
        return reverse("donations:detail", kwargs={"pk": self.pk})

    def __str__(self) -> str:
        return f"{self.food_name} ({self.quantity_display})"


class DonationRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"
        FULFILLED = "fulfilled", "Fulfilled"

    donation = models.ForeignKey(
        FoodDonation, on_delete=models.CASCADE, related_name="requests"
    )
    ngo = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="donation_requests",
        limit_choices_to={"role": "ngo"},
    )
    quantity = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.1"))],
        help_text="Quantity required by the NGO.",
    )
    message = models.TextField(
        blank=True, help_text="Tell the donor how the food will be used."
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    donor_note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["donation", "ngo"], name="unique_ngo_request_per_donation"
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="request_quantity_positive"
            ),
        ]

    @property
    def status_css(self) -> str:
        return {
            self.Status.PENDING: "warning",
            self.Status.ACCEPTED: "success",
            self.Status.REJECTED: "danger",
            self.Status.CANCELLED: "secondary",
            self.Status.EXPIRED: "danger",
            self.Status.FULFILLED: "success",
        }.get(self.status, "secondary")

    @property
    def is_pending(self) -> bool:
        return self.status == self.Status.PENDING

    def clean(self):
        errors = {}
        if self.donation_id and self.quantity:
            if self.quantity > self.donation.quantity:
                errors["quantity"] = "Requested quantity cannot exceed the donated quantity."
            if not self.donation.can_be_requested:
                errors["donation"] = "This donation is no longer available to request."
        if self.ngo_id and getattr(self.ngo, "role", None) != "ngo":
            errors["ngo"] = "Only NGO accounts can request donations."
        if errors:
            raise ValidationError(errors)

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if self.donation_id and quantity > self.donation.quantity:
            raise ValidationError("Requested quantity cannot exceed the donated quantity.")
        return quantity

    def __str__(self) -> str:
        return f"{self.ngo.display_name} → {self.donation.food_name}"
