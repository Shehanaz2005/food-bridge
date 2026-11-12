from django.contrib.auth.models import AbstractUser
from django.db import models
from django.urls import reverse
from django.utils import timezone

from donations.constants import FOOD_CATEGORY_CHOICES, FOOD_UNIT_CHOICES

from .validators import validate_image_file


class User(AbstractUser):
    """Single authentication model for every Food Bridge role."""

    class Role(models.TextChoices):
        DONOR = "donor", "Food Donor"
        NGO = "ngo", "NGO"
        VOLUNTEER = "volunteer", "Volunteer"
        ADMIN = "admin", "Administrator"

    email = models.EmailField("email address", unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.DONOR)
    phone = models.CharField(max_length=20, blank=True)
    city = models.CharField(max_length=100, blank=True)
    address = models.TextField(blank=True)
    avatar = models.ImageField(
        upload_to="avatars/%Y/%m/", blank=True, validators=[validate_image_file]
    )
    is_blocked = models.BooleanField(
        default=False, help_text="Blocked accounts cannot sign in or use the platform."
    )
    blocked_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_joined"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=["donor", "ngo", "volunteer", "admin"]),
                name="valid_user_role",
            )
        ]

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = self.Role.ADMIN
        super().save(*args, **kwargs)

    @property
    def is_admin_user(self) -> bool:
        return self.is_staff or self.role == self.Role.ADMIN

    @property
    def display_name(self) -> str:
        full_name = self.get_full_name().strip()
        if full_name:
            return full_name
        if self.role == self.Role.NGO:
            profile = getattr(self, "ngo_profile", None)
            if profile and profile.organization_name:
                return profile.organization_name
        if self.role == self.Role.DONOR:
            profile = getattr(self, "donor_profile", None)
            if profile and profile.organization_name:
                return profile.organization_name
        return self.username

    @property
    def initials(self) -> str:
        source = self.display_name.strip()
        parts = [part for part in source.replace("_", " ").split() if part]
        if len(parts) >= 2:
            return f"{parts[0][0]}{parts[1][0]}".upper()
        return source[:2].upper() or "FB"

    @property
    def dashboard_url(self) -> str:
        if self.is_admin_user:
            return reverse("accounts:admin_dashboard")
        if self.role == self.Role.NGO:
            return reverse("accounts:ngo_dashboard")
        if self.role == self.Role.VOLUNTEER:
            return reverse("accounts:volunteer_dashboard")
        return reverse("accounts:donor_dashboard")

    def __str__(self) -> str:
        return f"{self.display_name} ({self.get_role_display()})"


class DonorProfile(models.Model):
    class DonorType(models.TextChoices):
        RESTAURANT = "restaurant", "Restaurant / Cafe"
        HOTEL = "hotel", "Hotel / Caterer"
        EVENT = "event", "Event Organizer"
        INDIVIDUAL = "individual", "Individual"
        OTHER = "other", "Other Business"

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="donor_profile"
    )
    donor_type = models.CharField(
        max_length=20, choices=DonorType.choices, default=DonorType.INDIVIDUAL
    )
    organization_name = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.organization_name or self.user.display_name


class NGOProfile(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="ngo_profile"
    )
    organization_name = models.CharField(max_length=150)
    registration_number = models.CharField(max_length=80, blank=True)
    description = models.TextField(blank=True)
    contact_person = models.CharField(max_length=120, blank=True)
    website = models.URLField(blank=True)
    service_area = models.CharField(
        max_length=150, blank=True, help_text="Areas where the NGO can collect food."
    )
    preferred_categories = models.JSONField(
        default=list,
        blank=True,
        help_text="Food categories this NGO usually distributes.",
    )
    minimum_quantity = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0,
        help_text="Preferred minimum donation quantity.",
    )
    minimum_unit = models.CharField(
        max_length=20,
        choices=FOOD_UNIT_CHOICES,
        default="kg",
        help_text="Unit used for the preferred minimum quantity.",
    )
    verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_ngos",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization_name"]

    @property
    def preferred_category_labels(self) -> list[str]:
        labels = dict(FOOD_CATEGORY_CHOICES)
        return [labels.get(code, code) for code in self.preferred_categories]

    def __str__(self) -> str:
        return self.organization_name


class VolunteerProfile(models.Model):
    class Vehicle(models.TextChoices):
        FOOT = "foot", "On Foot"
        BIKE = "bike", "Bicycle / Motorbike"
        CAR = "car", "Car"
        VAN = "van", "Van / Truck"

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="volunteer_profile"
    )
    vehicle_type = models.CharField(
        max_length=20, choices=Vehicle.choices, default=Vehicle.BIKE
    )
    service_area = models.CharField(max_length=150, blank=True)
    is_available = models.BooleanField(
        default=True, help_text="Uncheck while you are unavailable for pickups."
    )
    bio = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def completed_count(self) -> int:
        return self.user.volunteer_assignments.filter(status="completed").count()

    @property
    def active_count(self) -> int:
        return self.user.volunteer_assignments.filter(
            status__in=["offered", "accepted", "picked_up"]
        ).count()

    def __str__(self) -> str:
        return f"Volunteer: {self.user.display_name}"
