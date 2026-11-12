from django import forms
from django.db.models import Q

from accounts.forms import BootstrapFormMixin
from donations.models import FoodDonation

from .models import IssueReport


class IssueFilterForm(BootstrapFormMixin, forms.Form):
    status = forms.ChoiceField(
        required=False,
        choices=[
            ("", "All issues"),
            ("open", "Open"),
            ("in_review", "In Review"),
            ("resolved", "Resolved"),
            ("dismissed", "Dismissed"),
        ],
    )
    q = forms.CharField(required=False, label="Search")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["q"].widget.attrs["placeholder"] = "Subject or reporter"
        self._style()


class IssueReportForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = IssueReport
        fields = ["category", "subject", "description", "related_donation"]
        widgets = {
            "description": forms.Textarea(
                attrs={"rows": 5, "placeholder": "Explain what happened and when."}
            )
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        queryset = FoodDonation.objects.none()
        if user and user.is_authenticated:
            if user.is_staff:
                queryset = FoodDonation.objects.all()
            elif user.role == "donor":
                queryset = FoodDonation.objects.filter(donor=user)
            elif user.role == "ngo":
                queryset = FoodDonation.objects.filter(requests__ngo=user).distinct()
            elif user.role == "volunteer":
                queryset = FoodDonation.objects.filter(assignment__volunteer=user)
        self.fields["related_donation"].queryset = queryset.order_by("-created_at")
        self.fields["related_donation"].required = False
        self.fields["related_donation"].error_messages["invalid_choice"] = (
            "You can only link an issue to your own donation activity."
        )
        self._style()

    def clean_related_donation(self):
        donation = self.cleaned_data.get("related_donation")
        raw_value = self.data.get(self.add_prefix("related_donation"))
        if not raw_value:
            return donation
        try:
            raw_pk = int(raw_value)
        except (TypeError, ValueError):
            return donation

        user = self.user
        if user is None or user.is_staff:
            return donation

        # A tampered/foreign ID is already rejected by the restricted
        # queryset; catch it here too so the user gets a clear explanation.
        allowed = (
            FoodDonation.objects.filter(pk=raw_pk)
            .filter(
                Q(donor=user)
                | Q(requests__ngo=user)
                | Q(assignment__volunteer=user)
            )
            .exists()
        )
        if not allowed:
            raise forms.ValidationError(
                "You can only link an issue to your own donation activity."
            )
        return donation


class AdminIssueUpdateForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = IssueReport
        fields = ["status", "admin_notes"]
        widgets = {"admin_notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()
