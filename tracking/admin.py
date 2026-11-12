from django.contrib import admin

from .models import AuditLog, DonationTracking


@admin.register(DonationTracking)
class DonationTrackingAdmin(admin.ModelAdmin):
    list_display = ("donation", "status", "title", "actor", "created_at")
    list_filter = ("status",)
    search_fields = ("donation__food_name", "title", "description")
    readonly_fields = ("donation", "status", "title", "description", "actor", "created_at")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "actor", "model_name", "object_id", "ip_address", "created_at")
    list_filter = ("action", "model_name")
    search_fields = ("description", "actor__username", "object_id")
    readonly_fields = (
        "actor",
        "action",
        "model_name",
        "object_id",
        "description",
        "ip_address",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
