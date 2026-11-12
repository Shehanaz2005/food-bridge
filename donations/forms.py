from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.forms import BootstrapFormMixin
from accounts.validators import ALLOWED_IMAGE_EXTENSIONS, MAX_IMAGE_SIZE

from .constants import FOOD_CATEGORY_CHOICES, FOOD_UNIT_CHOICES
from .models import DonationRequest, FoodDonation


class DonationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = FoodDonation
        fields = [
            "food_name",
            "category",
            "description",
            "quantity",
            "unit",
            "image",
            "is_vegetarian",
            "prepared_at",
            "expires_at",
            "pickup_address",
            "pickup_city",
            "pickup_contact_name",
            "pickup_contact_phone",
            "handling_instructions",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "handling_instructions": forms.Textarea(attrs={"rows": 3}),
            "pickup_address": forms.Textarea(attrs={"rows": 2}),
            "prepared_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "expires_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "image": forms.FileInput(
                attrs={"accept": "image/jpeg,image/png,image/webp"}
            ),
            "quantity": forms.NumberInput(attrs={"step": "0.01", "min": "0.1"}),
        }
        labels = {
            "prepared_at": "Food prepared / packed at",
            "expires_at": "Best before / expiry time",
            "is_vegetarian": "This food is vegetarian",
            "pickup_contact_name": "Pickup contact name",
            "pickup_contact_phone": "Pickup contact phone",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["prepared_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["expires_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["image"].help_text = (
            f"JPG, PNG, or WebP. Maximum {MAX_IMAGE_SIZE // (1024 * 1024)} MB."
        )
        self._style()
        self.fields["image"].widget.attrs["data-image-input"] = "true"

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if not image or not hasattr(image, "name"):
            return image
        suffix = "." + image.name.rsplit(".", 1)[-1].lower() if "." in image.name else ""
        if suffix not in ALLOWED_IMAGE_EXTENSIONS:
            raise ValidationError("Upload a JPG, PNG, or WebP image.")
        if image.size > MAX_IMAGE_SIZE:
            raise ValidationError("Image size must be 5 MB or smaller.")
        return image

    def clean(self):
        cleaned = super().clean()
        prepared = cleaned.get("prepared_at")
        expires = cleaned.get("expires_at")
        now = timezone.now()

        if prepared and expires:
            if expires <= prepared:
                self.add_error("expires_at", "Best-before time must be after preparation time.")
            elif expires <= now:
                self.add_error("expires_at", "Best-before time must be in the future.")
            elif (prepared - now).total_seconds() > 3600:
                self.add_error(
                    "prepared_at",
                    "Preparation time cannot be more than one hour in the future.",
                )

        quantity = cleaned.get("quantity")
        if quantity is not None and quantity < Decimal("0.1"):
            self.add_error("quantity", "Quantity must be at least 0.1.")
        return cleaned


class DonationRequestForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = DonationRequest
        fields = ["quantity", "message"]
        widgets = {
            "message": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Tell the donor how this food will be used and when you can collect it.",
                }
            ),
            "quantity": forms.NumberInput(attrs={"step": "0.01", "min": "0.1"}),
        }

    def __init__(self, *args, donation=None, **kwargs):
        self.donation = donation
        super().__init__(*args, **kwargs)
        if donation:
            self.fields["quantity"].widget.attrs["max"] = str(donation.quantity)
            self.fields["quantity"].help_text = (
                f"Available: {donation.quantity_display}. You cannot request more than this amount."
            )
            self.fields["quantity"].initial = donation.quantity
        self._style()

    def clean_quantity(self):
        quantity = self.cleaned_data.get("quantity")
        if self.donation and quantity and quantity > self.donation.quantity:
            raise ValidationError("Requested quantity cannot exceed the donated quantity.")
        if quantity is not None and quantity < Decimal("0.1"):
            raise ValidationError("Quantity must be at least 0.1.")
        return quantity


class DonationFilterForm(BootstrapFormMixin, forms.Form):
    q = forms.CharField(required=False, label="Search")
    category = forms.ChoiceField(
        required=False, choices=[("", "All categories")] + FOOD_CATEGORY_CHOICES
    )
    city = forms.ChoiceField(required=False, choices=[("", "All cities")])
    unit = forms.ChoiceField(required=False, choices=[("", "Any unit")] + FOOD_UNIT_CHOICES)
    min_quantity = forms.DecimalField(required=False, min_value=Decimal("0"), label="Min quantity")
    max_quantity = forms.DecimalField(required=False, min_value=Decimal("0"), label="Max quantity")
    availability = forms.ChoiceField(
        required=False,
        choices=[
            ("", "All available food"),
            ("expiring_6", "Expiring within 6 hours"),
            ("expiring_24", "Expiring within 24 hours"),
            ("expiring_48", "Expiring within 48 hours"),
        ],
    )
    sort = forms.ChoiceField(
        required=False,
        choices=[
            ("match", "Best match for my NGO"),
            ("newest", "Recently added"),
            ("expiry", "Nearest expiry"),
            ("quantity", "Highest quantity"),
        ],
        initial="match",
    )

    def __init__(self, *args, **kwargs):
        cities = (
            FoodDonation.objects.available_for_request()
            .values_list("pickup_city", flat=True)
            .distinct()
            .order_by("pickup_city")
        )
        super().__init__(*args, **kwargs)
        self.fields["city"].choices = [("", "All cities")] + [(city, city) for city in cities if city]
        self.fields["q"].widget.attrs["placeholder"] = "Food name, description, or city"
        if "sort" not in (self.data or {}) and "sort" not in (self.initial or {}):
            self.fields["sort"].initial = "match"
        self._style()

    def clean(self):
        cleaned = super().clean()
        minimum = cleaned.get("min_quantity")
        maximum = cleaned.get("max_quantity")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValidationError("Minimum quantity cannot be greater than maximum quantity.")
        return cleaned


class CancelDonationForm(BootstrapFormMixin, forms.Form):
    reason = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        label="Reason (optional)",
    )


class AdminDonationFilterForm(BootstrapFormMixin, forms.Form):
    q = forms.CharField(required=False, label="Search")
    status = forms.ChoiceField(
        required=False,
        choices=[("", "All statuses")] + list(FoodDonation.Status.choices),
    )
    category = forms.ChoiceField(
        required=False, choices=[("", "All categories")] + FOOD_CATEGORY_CHOICES
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["q"].widget.attrs["placeholder"] = "Food name, donor, or city"
        self._style()

    def filter(self, queryset):
        from django.db.models import Q

        q = (self.cleaned_data.get("q") or "").strip()
        status = self.cleaned_data.get("status")
        category = self.cleaned_data.get("category")
        if q:
            queryset = queryset.filter(
                Q(food_name__icontains=q)
                | Q(pickup_city__icontains=q)
                | Q(donor__username__icontains=q)
                | Q(donor__donor_profile__organization_name__icontains=q)
            )
        if status:
            queryset = queryset.filter(status=status)
        if category:
            queryset = queryset.filter(category=category)
        return queryset


class AdminRequestFilterForm(BootstrapFormMixin, forms.Form):
    status = forms.ChoiceField(
        required=False,
        choices=[("", "All request statuses")] + list(DonationRequest.Status.choices),
    )
    q = forms.CharField(required=False, label="Search")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["q"].widget.attrs["placeholder"] = "NGO or food name"
        self._style()
