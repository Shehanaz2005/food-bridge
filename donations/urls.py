from django.urls import path

from . import views

app_name = "donations"

urlpatterns = [
    path("", views.donor_donations, name="list"),
    path("new/", views.donation_create, name="create"),
    path("browse/", views.browse_donations, name="browse"),
    path("requests/", views.ngo_requests, name="requests"),
    path("history/", views.history, name="history"),
    path("<int:pk>/", views.donation_detail, name="detail"),
    path("<int:pk>/edit/", views.donation_edit, name="edit"),
    path("<int:pk>/cancel/", views.donation_cancel, name="cancel"),
    path("<int:pk>/request/", views.submit_request, name="request"),
    path(
        "<int:pk>/requests/<int:request_id>/accept/",
        views.accept_donation_request,
        name="request_accept",
    ),
    path(
        "<int:pk>/requests/<int:request_id>/reject/",
        views.reject_donation_request,
        name="request_reject",
    ),
    path(
        "<int:pk>/requests/<int:request_id>/cancel/",
        views.cancel_donation_request,
        name="request_cancel",
    ),
    path("<int:pk>/confirm/", views.confirm_receipt, name="confirm"),
    # Admin monitoring
    path("manage/all/", views.admin_donations, name="admin_donations"),
    path("manage/requests/", views.admin_requests, name="admin_requests"),
]
