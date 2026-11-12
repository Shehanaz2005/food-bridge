from django.urls import path

from . import views

app_name = "volunteers"

urlpatterns = [
    path("assignments/", views.assignment_list, name="assignments"),
    path("assignments/<int:pk>/", views.assignment_detail, name="assignment_detail"),
    path("assignments/<int:pk>/accept/", views.accept_assignment, name="accept"),
    path("assignments/<int:pk>/decline/", views.decline_assignment, name="decline"),
    path("assignments/<int:pk>/pickup/", views.mark_pickup, name="pickup"),
    path("assignments/<int:pk>/deliver/", views.mark_delivery, name="deliver"),
    path("history/", views.volunteer_history, name="history"),
]
