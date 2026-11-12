"""Authentication and profile forms."""

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db.models import Q

from donations.constants import FOOD_CATEGORY_CHOICES, FOOD_UNIT_CHOICES

from .models import DonorProfile, NGOProfile, User, VolunteerProfile

LOCKOUT_CACHE_PREFIX = "login-failures:"
MAX_LOGIN_FAILURES = 5


class BootstrapFormMixin:
    """Apply consistent Bootstrap classes to every widget."""

    def _style(self):
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.CheckboxSelectMultiple):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            elif isinstance(widget, forms.FileInput):
                widget.attrs.setdefault("class", "form-control")
            elif isinstance(widget, forms.RadioSelect):
                widget.attrs.setdefault("class", "form-check-input")
            else:
                widget.attrs.setdefault("class", "form-control")

            if field.required and not isinstance(
                widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple, forms.RadioSelect)
            ):
                widget.attrs.setdefault("required", "required")


class RegistrationForm(BootstrapFormMixin, UserCreationForm):
    role = forms.ChoiceField(
        choices=[
            (User.Role.DONOR, "Food Donor"),
            (User.Role.NGO, "NGO"),
            (User.Role.VOLUNTEER, "Volunteer"),
        ],
        initial=User.Role.DONOR,
        widget=forms.RadioSelect,
    )
    organization_name = forms.CharField(max_length=150, required=False)
    donor_type = forms.ChoiceField(
        choices=DonorProfile.DonorType.choices,
        required=False,
        initial=DonorProfile.DonorType.INDIVIDUAL,
    )
    registration_number = forms.CharField(max_length=80, required=False)
    vehicle_type = forms.ChoiceField(
        choices=VolunteerProfile.Vehicle.choices,
        required=False,
        initial=VolunteerProfile.Vehicle.BIKE,
    )
    terms = forms.BooleanField(
        label="I agree to Food Bridge's food-safety and community guidelines."
    )

    class Meta:
        model = User
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "phone",
            "city",
            "address",
        ]
        labels = {
            "first_name": "First name",
            "last_name": "Last name",
            "city": "City",
            "address": "Address",
        }

    field_order = [
        "role",
        "username",
        "first_name",
        "last_name",
        "email",
        "phone",
        "city",
        "address",
        "organization_name",
        "donor_type",
        "registration_number",
        "vehicle_type",
        "password1",
        "password2",
        "terms",
    ]

    def __init__(self, *args, **kwargs):
        initial = kwargs.get("initial") or {}
        requested_role = initial.get("role")
        if not requested_role and "data" not in kwargs and "request" in kwargs:
            pass
        super().__init__(*args, **kwargs)
        if requested_role in dict(self.fields["role"].choices):
            self.fields["role"].initial = requested_role
        self.fields["username"].widget.attrs.update({"autocomplete": "username"})
        self.fields["password1"].widget.attrs.update({"autocomplete": "new-password"})
        self.fields["password2"].widget.attrs.update({"autocomplete": "new-password"})
        self.fields["email"].widget.attrs.update({"autocomplete": "email"})
        self.fields["city"].required = True
        self._style()
        self.fields["terms"].widget.attrs.update({"class": "form-check-input"})

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email already exists.")
        return email

    def clean(self):
        cleaned = super().clean()
        role = cleaned.get("role")
        organization_name = (cleaned.get("organization_name") or "").strip()
        city = (cleaned.get("city") or "").strip()

        if not cleaned.get("terms"):
            self.add_error("terms", "Please accept the community guidelines to continue.")

        if role == User.Role.NGO:
            if not organization_name:
                self.add_error("organization_name", "NGOs must provide an organisation name.")
            if not city:
                self.add_error("city", "Enter the city where your NGO operates.")
        elif role == User.Role.DONOR:
            donor_type = cleaned.get("donor_type")
            if donor_type in {"restaurant", "hotel", "event", "other"} and not organization_name:
                self.add_error(
                    "organization_name",
                    "Enter your business or organisation name for this donor type.",
                )
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = self.cleaned_data["role"]
        user.email = self.cleaned_data["email"].strip().lower()
        user.phone = self.cleaned_data.get("phone", "").strip()
        user.city = self.cleaned_data.get("city", "").strip()
        user.address = self.cleaned_data.get("address", "").strip()
        if commit:
            user.save()
            self._save_profile(user)
        return user

    def _save_profile(self, user):
        organization_name = (self.cleaned_data.get("organization_name") or "").strip()
        if user.role == User.Role.DONOR:
            profile, _ = DonorProfile.objects.get_or_create(user=user)
            profile.donor_type = self.cleaned_data.get("donor_type") or DonorProfile.DonorType.INDIVIDUAL
            profile.organization_name = organization_name
            profile.save()
        elif user.role == User.Role.NGO:
            profile, _ = NGOProfile.objects.get_or_create(
                user=user, defaults={"organization_name": organization_name or user.username}
            )
            profile.organization_name = organization_name or user.username
            profile.registration_number = self.cleaned_data.get("registration_number", "").strip()
            profile.save()
        elif user.role == User.Role.VOLUNTEER:
            profile, _ = VolunteerProfile.objects.get_or_create(user=user)
            profile.vehicle_type = self.cleaned_data.get("vehicle_type") or VolunteerProfile.Vehicle.BIKE
            profile.service_area = user.city
            profile.save()


class FoodBridgeLoginForm(BootstrapFormMixin, AuthenticationForm):
    username = forms.CharField(
        label="Username or email",
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}),
    )

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request=request, *args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {"placeholder": "you@example.com", "class": "form-control"}
        )
        self.fields["password"].widget.attrs.update(
            {"placeholder": "Your password", "class": "form-control", "autocomplete": "current-password"}
        )
        self._style()

    def clean(self):
        identifier = (self.cleaned_data.get("username") or "").strip()
        key = f"{LOCKOUT_CACHE_PREFIX}{identifier.casefold()}"
        if identifier and cache.get(key, 0) >= MAX_LOGIN_FAILURES:
            raise ValidationError(
                "Too many failed sign-in attempts. Please wait 15 minutes and try again.",
                code="login_locked",
            )

        if "@" in identifier:
            matched = User.objects.filter(email__iexact=identifier).only("username").first()
            if matched:
                self.cleaned_data["username"] = matched.username
                self.data = self.data.copy()
                self.data["username"] = matched.username

        return super().clean()

    def confirm_login_allowed(self, user):
        if user.is_blocked:
            reason = f" Reason: {user.blocked_reason}" if user.blocked_reason else ""
            raise ValidationError(
                "This account has been blocked by the Food Bridge team."
                f"{reason} Contact support if you believe this is a mistake.",
                code="blocked_account",
            )
        if not user.is_active:
            raise ValidationError("This account is inactive.", code="inactive")
        return super().confirm_login_allowed(user)


class UserProfileForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone", "city", "address", "avatar"]
        widgets = {
            "address": forms.Textarea(attrs={"rows": 2}),
            "avatar": forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()
        self.fields["email"].required = True
        self.fields["city"].required = True

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError("Another account already uses this email.")
        return email


class DonorProfileForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = DonorProfile
        fields = ["organization_name", "donor_type"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class NGOProfileForm(BootstrapFormMixin, forms.ModelForm):
    preferred_categories = forms.MultipleChoiceField(
        choices=FOOD_CATEGORY_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Used by Smart Food Matching to rank suitable donations.",
    )

    class Meta:
        model = NGOProfile
        fields = [
            "organization_name",
            "registration_number",
            "description",
            "contact_person",
            "website",
            "service_area",
            "preferred_categories",
            "minimum_quantity",
            "minimum_unit",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["preferred_categories"].initial = list(
            self.instance.preferred_categories or []
        )
        self._style()
        self.fields["organization_name"].required = True

    def clean_preferred_categories(self):
        selected = self.cleaned_data.get("preferred_categories") or []
        valid = {code for code, _ in FOOD_CATEGORY_CHOICES}
        return [code for code in selected if code in valid]

    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.preferred_categories = self.cleaned_data.get("preferred_categories", [])
        if commit:
            profile.save()
            self.save_m2m()
        return profile


class VolunteerProfileForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = VolunteerProfile
        fields = ["vehicle_type", "service_area", "is_available", "bio"]
        widgets = {"bio": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class AdminUserFilterForm(BootstrapFormMixin, forms.Form):
    q = forms.CharField(required=False, label="Search")
    role = forms.ChoiceField(
        required=False,
        choices=[("", "All roles")] + list(User.Role.choices),
    )
    status = forms.ChoiceField(
        required=False,
        choices=[
            ("", "All accounts"),
            ("active", "Active"),
            ("blocked", "Blocked"),
            ("unverified", "Unverified NGOs"),
        ],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["q"].widget.attrs["placeholder"] = "Name, username, or email"
        self._style()

    def filter(self, queryset):
        q = (self.cleaned_data.get("q") or "").strip()
        role = self.cleaned_data.get("role")
        status = self.cleaned_data.get("status")
        if q:
            queryset = queryset.filter(
                Q(username__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(email__icontains=q)
                | Q(ngo_profile__organization_name__icontains=q)
                | Q(donor_profile__organization_name__icontains=q)
            )
        if role:
            queryset = queryset.filter(role=role)
        if status == "active":
            queryset = queryset.filter(is_blocked=False)
        elif status == "blocked":
            queryset = queryset.filter(is_blocked=True)
        elif status == "unverified":
            queryset = queryset.filter(role=User.Role.NGO, ngo_profile__verified=False)
        return queryset
