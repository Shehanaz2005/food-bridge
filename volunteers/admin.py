from django.contrib import admin

from .models import PickupAssignment


@admin.register(PickupAssignment)
class PickupAssignmentAdmin(admin.ModelAdmin):
    list_display = ("donation", "volunteer", "status", "assigned_by", "created_at")
    list_filter = ("status",)
    search_fields = ("donation__food_name", "volunteer__username", "volunteer__first_name")
    readonly_fields = (
        "accepted_at",
        "picked_up_at",
        "delivered_at",
        "completed_at",
        "created_at",
        "updated_at",
    )
