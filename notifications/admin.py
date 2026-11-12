from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "title", "level", "is_read", "created_at")
    list_filter = ("level", "is_read")
    search_fields = ("user__username", "title", "message")
    readonly_fields = ("user", "title", "message", "level", "url", "event_key", "created_at")
