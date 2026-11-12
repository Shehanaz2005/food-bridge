from django.contrib import admin

from .models import IssueReport


@admin.register(IssueReport)
class IssueReportAdmin(admin.ModelAdmin):
    list_display = ("subject", "reporter", "category", "status", "created_at", "resolved_by")
    list_filter = ("status", "category")
    search_fields = ("subject", "description", "reporter__username")
    readonly_fields = ("created_at", "updated_at", "resolved_at")
