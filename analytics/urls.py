from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path("", views.home, name="home"),
    path("impact/", views.impact, name="impact"),
    path("food-safety/", views.food_safety, name="food_safety"),
    path("privacy/", views.privacy, name="privacy"),
    path("terms/", views.terms, name="terms"),
    path("dashboard/admin/analytics/", views.admin_analytics, name="admin_analytics"),
]
