from django.contrib import admin

from .models import DonationRequest, FoodDonation


class DonationRequestInline(admin.TabularInline):
    model = DonationRequest
    extra = 0
    readonly_fields = ("created_at", "updated_at", "responded_at")


@admin.register(FoodDonation)
class FoodDonationAdmin(admin.ModelAdmin):
    list_display = (
        "food_name",
        "donor",
        "category",
        "quantity",
        "unit",
        "pickup_city",
        "status",
        "expires_at",
        "created_at",
    )
    list_filter = ("status", "category", "unit", "pickup_city", "is_vegetarian")
    search_fields = ("food_name", "description", "donor__username", "pickup_address")
    readonly_fields = ("created_at", "updated_at", "completed_at")
    date_hierarchy = "created_at"
    inlines = [DonationRequestInline]
    list_per_page = 25


@admin.register(DonationRequest)
class DonationRequestAdmin(admin.ModelAdmin):
    list_display = ("donation", "ngo", "quantity", "status", "created_at", "responded_at")
    list_filter = ("status",)
    search_fields = ("donation__food_name", "ngo__username", "ngo__ngo_profile__organization_name")
    readonly_fields = ("created_at", "updated_at", "responded_at")
