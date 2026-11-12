from django import forms

from accounts.forms import BootstrapFormMixin
from accounts.models import VolunteerProfile


class AssignVolunteerForm(BootstrapFormMixin, forms.Form):
    volunteer = forms.ModelChoiceField(
        queryset=VolunteerProfile.objects.none(),
        label="Volunteer",
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 2, "placeholder": "Pickup instructions or timing notes."}
        ),
    )

    def __init__(self, *args, donation=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = (
            VolunteerProfile.objects.select_related("user")
            .filter(user__is_blocked=False, is_available=True)
            .order_by("user__first_name")
        )
        self.fields["volunteer"].queryset = queryset
        if donation:
            self.fields["volunteer"].label_from_instance = (
                lambda profile: f"{profile.user.display_name} · {profile.user.city or 'No city'} · "
                f"{profile.get_vehicle_type_display()} · {profile.completed_count} completed"
            )
        self._style()
