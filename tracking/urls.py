from django.urls import path

from . import views

app_name = "tracking"

urlpatterns = [
    path("api/donations/<int:pk>/status/", views.donation_status, name="status"),
]
