from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import DonorProfile, NGOProfile, User, VolunteerProfile


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "username",
        "email",
        "role",
        "display_name",
        "is_blocked",
        "is_staff",
        "date_joined",
    )
    list_filter = ("role", "is_blocked", "is_staff", "is_active")
    search_fields = ("username", "email", "first_name", "last_name", "phone")
    ordering = ("-date_joined",)
    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "Food Bridge access",
            {
                "fields": (
                    "role",
                    "phone",
                    "city",
                    "address",
                    "avatar",
                    "is_blocked",
                    "blocked_reason",
                )
            },
        ),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        (
            "Food Bridge access",
            {"fields": ("email", "role", "phone", "city")},
        ),
    )


@admin.register(DonorProfile)
class DonorProfileAdmin(admin.ModelAdmin):
    list_display = ("organization_name", "user", "donor_type", "updated_at")
    list_filter = ("donor_type",)
    search_fields = ("organization_name", "user__username", "user__email")


@admin.register(NGOProfile)
class NGOProfileAdmin(admin.ModelAdmin):
    list_display = ("organization_name", "user", "verified", "verified_at", "updated_at")
    list_filter = ("verified",)
    search_fields = ("organization_name", "registration_number", "user__username", "user__email")
    actions = ["mark_verified"]

    @admin.action(description="Mark selected NGOs as verified")
    def mark_verified(self, request, queryset):
        from django.utils import timezone

        updated = queryset.update(
            verified=True, verified_at=timezone.now(), verified_by=request.user
        )
        self.message_user(request, f"{updated} NGO(s) verified.")


@admin.register(VolunteerProfile)
class VolunteerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "vehicle_type", "service_area", "is_available", "updated_at")
    list_filter = ("is_available", "vehicle_type")
    search_fields = ("user__username", "user__first_name", "user__last_name", "service_area")
