from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register, name="register"),
    path("login/", views.FoodBridgeLoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile, name="profile"),
    path("password/", views.FoodBridgePasswordChangeView.as_view(), name="password_change"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/donor/", views.donor_dashboard, name="donor_dashboard"),
    path("dashboard/ngo/", views.ngo_dashboard, name="ngo_dashboard"),
    path("dashboard/volunteer/", views.volunteer_dashboard, name="volunteer_dashboard"),
    path("dashboard/admin/", views.admin_dashboard, name="admin_dashboard"),
    path("dashboard/admin/users/", views.admin_users, name="admin_users"),
    path("dashboard/admin/users/<int:pk>/", views.admin_user_detail, name="admin_user_detail"),
    path("dashboard/admin/users/<int:pk>/verify/", views.verify_ngo, name="verify_ngo"),
    path("dashboard/admin/users/<int:pk>/block/", views.toggle_block_user, name="block_user"),
    path(
        "dashboard/volunteer/availability/",
        views.toggle_volunteer_availability,
        name="toggle_availability",
    ),
]
