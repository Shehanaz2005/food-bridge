from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.core.cache import cache
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from datetime import timedelta

from analytics.services import (
    donor_impact,
    get_admin_snapshot,
    ngo_impact,
    volunteer_impact,
)
from donations.expiry import expire_overdue_donations
from donations.matching import rank_donations_for_ngo
from donations.models import DonationRequest, FoodDonation
from notifications.models import Notification
from notifications.services import notify
from support.models import IssueReport
from tracking.models import DonationTracking
from tracking.services import log_audit

from .decorators import admin_required, role_required
from .forms import (
    AdminUserFilterForm,
    DonorProfileForm,
    FoodBridgeLoginForm,
    NGOProfileForm,
    RegistrationForm,
    UserProfileForm,
    VolunteerProfileForm,
)
from .models import NGOProfile, User


def dashboard(request):
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    return redirect(request.user.dashboard_url)


def home_redirect(request):
    return redirect("analytics:home")


def _safe_next(request, fallback):
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(target)
    return redirect(fallback)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def register(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    requested_role = request.GET.get("role", User.Role.DONOR)
    initial = {"role": requested_role} if requested_role in dict(User.Role.choices) else {}

    if request.method == "POST":
        form = RegistrationForm(request.POST)
    else:
        form = RegistrationForm(initial=initial)

    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        log_audit(
            actor=user,
            action="account_registered",
            obj=user,
            description=f"New {user.get_role_display()} account registered.",
            request=request,
        )
        notify(
            user,
            "Welcome to Food Bridge",
            "Thank you for joining the movement against food waste. "
            + (
                "Your NGO account is awaiting verification by our team. You can complete your "
                "profile now and start requesting food once approved."
                if user.role == User.Role.NGO
                else "Complete your profile and start making an impact today."
            ),
            level=Notification.Level.SUCCESS,
            url=reverse("accounts:profile"),
        )
        if user.role == User.Role.NGO:
            messages.info(
                request,
                "Your NGO account is pending verification. You can browse food now, but requests "
                "unlock after an administrator verifies your organisation.",
            )
        else:
            messages.success(request, f"Welcome to Food Bridge, {user.display_name}!")
        return redirect("accounts:dashboard")

    return render(request, "authentication/register.html", {"form": form})


class FoodBridgeLoginView(LoginView):
    template_name = "authentication/login.html"
    authentication_form = FoodBridgeLoginForm
    redirect_authenticated_user = True

    def form_invalid(self, form):
        identifier = (form.data.get("username") or "").strip().casefold()
        if identifier:
            key = f"login-failures:{identifier}"
            failures = cache.get(key, 0) + 1
            cache.set(key, failures, timeout=15 * 60)
            if failures >= 5:
                messages.error(
                    request=self.request,
                    message="Too many failed attempts. Sign-in is paused for 15 minutes.",
                )
        existing = User.objects.filter(username__iexact=form.data.get("username", "")).first()
        log_audit(
            actor=existing,
            action="login_failed",
            obj=existing,
            description="Failed sign-in attempt.",
            request=self.request,
        )
        return super().form_invalid(form)

    def form_valid(self, form):
        identifier = (form.cleaned_data.get("username") or "").strip().casefold()
        cache.delete(f"login-failures:{identifier}")
        messages.success(self.request, f"Welcome back, {form.get_user().display_name}!")
        log_audit(
            actor=form.get_user(),
            action="login_success",
            obj=form.get_user(),
            description="User signed in.",
            request=self.request,
        )
        return super().form_valid(form)


@require_POST
def logout_view(request):
    if request.user.is_authenticated:
        log_audit(
            actor=request.user,
            action="logout",
            obj=request.user,
            description="User signed out.",
            request=request,
        )
    logout(request)
    messages.success(request, "You have been signed out safely.")
    return redirect("analytics:home")


@login_required
def profile(request):
    user = request.user
    if user.role == User.Role.DONOR:
        profile_form = DonorProfileForm(
            request.POST or None, instance=user.donor_profile, prefix="profile"
        )
    elif user.role == User.Role.NGO:
        profile_form = NGOProfileForm(
            request.POST or None, instance=user.ngo_profile, prefix="profile"
        )
    elif user.role == User.Role.VOLUNTEER:
        profile_form = VolunteerProfileForm(
            request.POST or None, instance=user.volunteer_profile, prefix="profile"
        )
    else:
        profile_form = None

    user_form = UserProfileForm(request.POST or None, request.FILES or None, instance=user)

    if request.method == "POST":
        valid = user_form.is_valid() and (profile_form is None or profile_form.is_valid())
        if valid:
            user = user_form.save()
            if profile_form is not None:
                profile_form.save()
            messages.success(request, "Profile updated successfully.")
            log_audit(
                actor=user,
                action="profile_updated",
                obj=user,
                description="User updated their profile.",
                request=request,
            )
            return redirect("accounts:profile")
        messages.error(request, "Please correct the highlighted fields.")

    context = {
        "user_form": user_form,
        "profile_form": profile_form,
        "page_title": "My Profile",
        "active_nav": "profile",
    }
    return render(request, "accounts/profile.html", context)


class FoodBridgePasswordChangeView(PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"page_title": "Security", "active_nav": "profile"})
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        update_session_auth_hash(self.request, form.user)
        messages.success(self.request, "Your password has been updated.")
        log_audit(
            actor=self.request.user,
            action="password_changed",
            obj=self.request.user,
            description="User changed their password.",
            request=self.request,
        )
        return response


# ---------------------------------------------------------------------------
# Role dashboards
# ---------------------------------------------------------------------------
@role_required(User.Role.DONOR)
def donor_dashboard(request):
    expire_overdue_donations()
    user = request.user
    donations = user.donations.select_related("donor")
    stats = donor_impact(user)
    now = timezone.now()

    context = {
        "page_title": "Donor Dashboard",
        "active_nav": "dashboard",
        "stats": stats,
        "recent_donations": donations[:5],
        "expiring_donations": donations.active()
        .filter(expires_at__lte=now + timedelta(hours=12))
        .order_by("expires_at")[:4],
        "pending_requests": DonationRequest.objects.filter(
            donation__donor=user, status=DonationRequest.Status.PENDING
        )
        .select_related("ngo", "donation")
        .order_by("-created_at")[:6],
        "request_count": DonationRequest.objects.filter(donation__donor=user).count(),
        "recent_activity": DonationTracking.objects.filter(donation__donor=user)
        .select_related("donation", "actor")
        .order_by("-created_at")[:6],
    }
    return render(request, "dashboards/donor.html", context)


@role_required(User.Role.NGO)
def ngo_dashboard(request):
    expire_overdue_donations()
    user = request.user
    profile = user.ngo_profile
    available = (
        FoodDonation.objects.available_for_request()
        .select_related("donor", "donor__donor_profile")
        .prefetch_related("requests")
    )
    matches = rank_donations_for_ngo(available, user)[:4]
    active_requests = (
        user.donation_requests.select_related("donation", "donation__donor", "donation__assignment")
        .order_by("-created_at")
    )

    context = {
        "page_title": "NGO Dashboard",
        "active_nav": "dashboard",
        "profile": profile,
        "stats": ngo_impact(user),
        "matches": matches,
        "recent_requests": active_requests[:6],
        "active_pickups": active_requests.filter(
            status__in=[DonationRequest.Status.ACCEPTED],
            donation__status__in=[
                FoodDonation.Status.ACCEPTED,
                FoodDonation.Status.ASSIGNED,
                FoodDonation.Status.PICKED_UP,
                FoodDonation.Status.DELIVERED,
            ],
        )[:5],
    }
    return render(request, "dashboards/ngo.html", context)


@role_required(User.Role.VOLUNTEER)
def volunteer_dashboard(request):
    user = request.user
    assignments = user.volunteer_assignments.select_related(
        "donation", "donation__donor", "donation__donor__donor_profile"
    )
    context = {
        "page_title": "Volunteer Dashboard",
        "active_nav": "dashboard",
        "profile": user.volunteer_profile,
        "stats": volunteer_impact(user),
        "offered_assignments": assignments.filter(status="offered")[:6],
        "active_assignments": assignments.filter(
            status__in=["accepted", "picked_up", "delivered"]
        )[:6],
        "completed_assignments": assignments.filter(status="completed")[:5],
    }
    return render(request, "dashboards/volunteer.html", context)


@admin_required
def admin_dashboard(request):
    expire_overdue_donations()
    snapshot = get_admin_snapshot()
    awaiting = (
        FoodDonation.objects.filter(
            status=FoodDonation.Status.ACCEPTED,
            requests__status=DonationRequest.Status.ACCEPTED,
        )
        .select_related("donor")
        .distinct()
        .order_by("expires_at")[:6]
    )
    context = {
        "page_title": "Admin Dashboard",
        "active_nav": "dashboard",
        "snapshot": snapshot,
        "unverified_ngos": NGOProfile.objects.filter(verified=False)
        .select_related("user")
        .order_by("-created_at")[:6],
        "awaiting_assignment": awaiting,
        "recent_donations": FoodDonation.objects.select_related("donor").order_by("-created_at")[:6],
        "pending_requests": DonationRequest.objects.filter(
            status=DonationRequest.Status.PENDING
        )
        .select_related("ngo", "donation")
        .order_by("-created_at")[:6],
        "open_issues": IssueReport.objects.filter(
            status__in=[IssueReport.Status.OPEN, IssueReport.Status.IN_REVIEW]
        )
        .select_related("reporter")
        .order_by("-created_at")[:5],
        "recent_users": User.objects.order_by("-date_joined")[:5],
    }
    return render(request, "admin_dashboard/dashboard.html", context)


# ---------------------------------------------------------------------------
# Admin user management
# ---------------------------------------------------------------------------
@admin_required
def admin_users(request):
    form = AdminUserFilterForm(request.GET or None)
    queryset = User.objects.select_related("donor_profile", "ngo_profile", "volunteer_profile")
    if form.is_valid():
        queryset = form.filter(queryset)
    context = {
        "page_title": "Manage Users",
        "active_nav": "users",
        "form": form,
        "users": queryset.order_by("-date_joined")[:200],
        "total": queryset.count(),
    }
    return render(request, "admin_dashboard/users.html", context)


@admin_required
def admin_user_detail(request, pk):
    target = get_object_or_404(
        User.objects.select_related("donor_profile", "ngo_profile", "volunteer_profile"),
        pk=pk,
    )
    context = {
        "page_title": target.display_name,
        "active_nav": "users",
        "target": target,
        "donations": target.donations.select_related("donor")[:10] if target.role == "donor" else [],
        "requests": target.donation_requests.select_related("donation")[:10] if target.role == "ngo" else [],
        "assignments": target.volunteer_assignments.select_related("donation")[:10]
        if target.role == "volunteer"
        else [],
        "audit_entries": target.audit_actions.all()[:10],
        "issues": target.issues.select_related("related_donation")[:5],
    }
    return render(request, "admin_dashboard/user_detail.html", context)


@admin_required
@require_POST
def verify_ngo(request, pk):
    target = get_object_or_404(User, pk=pk, role=User.Role.NGO)
    profile = target.ngo_profile
    profile.verified = True
    profile.verified_at = timezone.now()
    profile.verified_by = request.user
    profile.save(update_fields=["verified", "verified_at", "verified_by", "updated_at"])
    notify(
        target,
        "NGO verification approved",
        "Your organisation has been verified. You can now request available food donations.",
        level=Notification.Level.SUCCESS,
        url=reverse("donations:browse"),
    )
    log_audit(
        actor=request.user,
        action="ngo_verified",
        obj=profile,
        description=f"Verified NGO {profile.organization_name}.",
        request=request,
    )
    messages.success(request, f"{profile.organization_name} is now verified.")
    return _safe_next(request, "accounts:admin_users")


@admin_required
@require_POST
def toggle_block_user(request, pk):
    target = get_object_or_404(User, pk=pk)
    if target == request.user or target.is_superuser:
        messages.error(request, "You cannot block this account.")
        return _safe_next(request, "accounts:admin_users")

    target.is_blocked = not target.is_blocked
    target.blocked_reason = request.POST.get("reason", "").strip()[:255] if target.is_blocked else ""
    target.save(update_fields=["is_blocked", "blocked_reason", "updated_at"])
    action = "account_blocked" if target.is_blocked else "account_unblocked"
    log_audit(
        actor=request.user,
        action=action,
        obj=target,
        description=f"{'Blocked' if target.is_blocked else 'Unblocked'} account {target.username}. "
        f"{target.blocked_reason}",
        request=request,
    )
    messages.success(
        request,
        f"{target.display_name} has been {'blocked' if target.is_blocked else 'unblocked'}.",
    )
    return _safe_next(request, "accounts:admin_users")


@role_required(User.Role.VOLUNTEER)
@require_POST
def toggle_volunteer_availability(request):
    profile = request.user.volunteer_profile
    profile.is_available = not profile.is_available
    profile.save(update_fields=["is_available", "updated_at"])
    messages.success(
        request,
        f"You are now {'available' if profile.is_available else 'unavailable'} for pickups.",
    )
    return _safe_next(request, "accounts:volunteer_dashboard")
