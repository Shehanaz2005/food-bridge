from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from donations import views as donation_views
from tracking import views as tracking_views
from volunteers import views as volunteer_views

admin.site.site_header = "Food Bridge Administration"
admin.site.site_title = "Food Bridge Admin"
admin.site.index_title = "Platform Management"

urlpatterns = [
    path("admin/", admin.site.urls),
    # Public pages: home and impact
    path("", include("analytics.urls")),
    path("accounts/", include("accounts.urls")),
    path("donations/", include("donations.urls")),
    path("volunteer/", include("volunteers.urls")),
    path("tracking/", include("tracking.urls")),
    path("notifications/", include("notifications.urls")),
    path("", include("support.urls")),
    # Custom admin operations (global names used from sidebars)
    path("dashboard/admin/donations/", donation_views.admin_donations, name="admin_donations"),
    path("dashboard/admin/requests/", donation_views.admin_requests, name="admin_requests"),
    path("dashboard/admin/assignments/", volunteer_views.admin_assignments, name="admin_assignments"),
    path(
        "dashboard/admin/assign/<int:donation_id>/",
        volunteer_views.admin_assign,
        name="admin_assign",
    ),
    path(
        "dashboard/admin/assign/<int:donation_id>/auto/",
        volunteer_views.admin_auto_assign,
        name="admin_auto_assign",
    ),
    path("dashboard/admin/audit/", tracking_views.admin_audit, name="admin_audit"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR / "static")

handler403 = "food_bridge.views.handler403"
handler404 = "food_bridge.views.handler404"
handler500 = "food_bridge.views.handler500"
