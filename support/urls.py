from django.urls import path

from . import views

app_name = "support"

urlpatterns = [
    path("support/report/", views.report_issue, name="report_issue"),
    path("dashboard/admin/issues/", views.admin_issues, name="admin_issues"),
    path("dashboard/admin/issues/<int:pk>/update/", views.admin_issue_update, name="admin_issue_update"),
]
