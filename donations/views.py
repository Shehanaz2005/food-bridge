from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import admin_required, role_required
from accounts.models import User
from analytics.services import donor_impact, ngo_impact
from tracking.services import build_journey, log_audit, record_event

from .expiry import expire_overdue_donations
from .forms import (
    AdminDonationFilterForm,
    AdminRequestFilterForm,
    CancelDonationForm,
    DonationFilterForm,
    DonationForm,
    DonationRequestForm,
)
from .matching import rank_donations_for_ngo, score_donation
from .models import DonationRequest, FoodDonation
from .permissions import (
    can_request_donation,
    can_view_donation,
    can_view_private_contact,
)
from .workflow import (
    accept_request,
    cancel_donation,
    cancel_request_by_ngo,
    complete_donation,
    create_donation_request,
    reject_request,
)


def _get_donation(pk):
    return get_object_or_404(
        FoodDonation.objects.select_related("donor", "donor__donor_profile"), pk=pk
    )


def _assignment_for(donation):
    try:
        return donation.assignment
    except Exception:
        return None


def _detail_context(request, donation, request_form=None):
    user = request.user
    profile = getattr(user, "ngo_profile", None)
    assignment = _assignment_for(donation)
    my_request = None
    if user.role == User.Role.NGO:
        my_request = donation.requests.filter(ngo=user).select_related("ngo").first()
    ngo_requests = (
        donation.requests.select_related("ngo", "ngo__ngo_profile").order_by("-created_at")
        if user.is_staff or donation.donor_id == user.pk
        else donation.requests.none()
    )
    accepted = donation.accepted_request
    can_confirm = donation.status == FoodDonation.Status.DELIVERED and (
        user.is_staff or (accepted and accepted.ngo_id == user.pk)
    )
    can_cancel = (
        user.is_staff or donation.donor_id == user.pk
    ) and donation.status in {
        FoodDonation.Status.AVAILABLE,
        FoodDonation.Status.REQUESTED,
        FoodDonation.Status.ACCEPTED,
        FoodDonation.Status.ASSIGNED,
    }
    if request_form is None and can_request_donation(user, donation):
        request_form = DonationRequestForm(donation=donation)

    return {
        "donation": donation,
        "assignment": assignment,
        "journey": build_journey(donation),
        "tracking_events": donation.tracking_events.select_related("actor").order_by(
            "-created_at", "-pk"
        )[:20],
        "my_request": my_request,
        "ngo_requests": ngo_requests,
        "accepted_request": accepted,
        "request_form": request_form,
        "can_request": can_request_donation(user, donation),
        "can_view_private": can_view_private_contact(user, donation),
        "can_confirm": can_confirm,
        "can_cancel": can_cancel,
        "can_assign": user.is_staff and donation.status == FoodDonation.Status.ACCEPTED,
        "match": score_donation(donation, user) if profile else None,
        "ngo_verified": bool(profile and profile.verified),
        "cancel_form": CancelDonationForm(),
        "status_url": reverse("tracking:status", kwargs={"pk": donation.pk}),
        "page_title": donation.food_name,
        "active_nav": "browse" if user.role == User.Role.NGO else "donations",
    }


# ---------------------------------------------------------------------------
# Donor
# ---------------------------------------------------------------------------
@role_required(User.Role.DONOR)
def donor_donations(request):
    expire_overdue_donations()
    queryset = request.user.donations.select_related("donor")
    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    if status in dict(FoodDonation.Status.choices):
        queryset = queryset.filter(status=status)
    if q:
        queryset = queryset.filter(
            Q(food_name__icontains=q) | Q(description__icontains=q) | Q(pickup_city__icontains=q)
        )
    queryset = queryset.order_by("-created_at")
    paginator = Paginator(queryset, 12)
    page_obj = paginator.get_page(request.GET.get("page"))
    context = {
        "page_title": "My Donations",
        "active_nav": "donations",
        "donations": page_obj.object_list,
        "page_obj": page_obj,
        "status_filter": status,
        "q": q,
        "statuses": FoodDonation.Status.choices,
        "stats": donor_impact(request.user),
    }
    return render(request, "donations/donor_list.html", context)


@role_required(User.Role.DONOR)
def donation_create(request):
    now = timezone.localtime()
    initial = {
        "prepared_at": now.replace(second=0, microsecond=0),
        "expires_at": now.replace(second=0, microsecond=0) + timedelta(hours=6),
        "pickup_contact_name": request.user.display_name,
        "pickup_contact_phone": request.user.phone,
        "pickup_city": request.user.city,
        "pickup_address": request.user.address,
    }
    if request.method == "POST":
        form = DonationForm(request.POST, request.FILES)
        if form.is_valid():
            donation = form.save(commit=False)
            donation.donor = request.user
            donation.save()
            record_event(
                donation,
                FoodDonation.Status.AVAILABLE,
                title="Donation created",
                description=f"{donation.quantity_display} of {donation.food_name} is available for rescue.",
                actor=request.user,
            )
            log_audit(
                actor=request.user,
                action="donation_created",
                obj=donation,
                description=f"Created donation “{donation.food_name}”.",
                request=request,
            )
            messages.success(
                request,
                "Your donation is live. Nearby NGOs can now discover and request it.",
            )
            return redirect("donations:detail", pk=donation.pk)
        messages.error(request, "Please correct the highlighted fields.")
    else:
        form = DonationForm(initial=initial)

    return render(
        request,
        "donations/form.html",
        {
            "form": form,
            "page_title": "Add Food Donation",
            "active_nav": "donations",
            "is_edit": False,
        },
    )


@role_required(User.Role.DONOR)
def donation_edit(request, pk):
    donation = _get_donation(pk)
    if donation.donor_id != request.user.pk:
        raise PermissionDenied("You can only edit your own donations.")
    if donation.status not in {FoodDonation.Status.AVAILABLE, FoodDonation.Status.REQUESTED}:
        messages.error(request, "This donation can no longer be edited because the workflow has advanced.")
        return redirect("donations:detail", pk=donation.pk)
    if donation.is_expired:
        messages.error(request, "Expired donations cannot be edited.")
        return redirect("donations:detail", pk=donation.pk)

    if request.method == "POST":
        form = DonationForm(request.POST, request.FILES, instance=donation)
        if form.is_valid():
            donation = form.save()
            log_audit(
                actor=request.user,
                action="donation_updated",
                obj=donation,
                description=f"Updated donation “{donation.food_name}”.",
                request=request,
            )
            messages.success(request, "Donation updated successfully.")
            return redirect("donations:detail", pk=donation.pk)
        messages.error(request, "Please correct the highlighted fields.")
    else:
        form = DonationForm(instance=donation)

    return render(
        request,
        "donations/form.html",
        {
            "form": form,
            "donation": donation,
            "page_title": "Edit Donation",
            "active_nav": "donations",
            "is_edit": True,
        },
    )


@login_required
def donation_detail(request, pk):
    expire_overdue_donations()
    donation = _get_donation(pk)
    if not can_view_donation(request.user, donation):
        raise PermissionDenied("You do not have access to this donation.")

    context = _detail_context(request, donation)
    return render(request, "donations/detail.html", context)


@login_required
@require_POST
def donation_cancel(request, pk):
    donation = _get_donation(pk)
    if donation.donor_id != request.user.pk and not request.user.is_staff:
        raise PermissionDenied("You cannot cancel this donation.")
    form = CancelDonationForm(request.POST)
    reason = request.POST.get("reason", "").strip()
    try:
        cancel_donation(donation.pk, request.user, reason)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect("donations:detail", pk=donation.pk)

    log_audit(
        actor=request.user,
        action="donation_cancelled",
        obj=donation,
        description=f"Cancelled donation “{donation.food_name}”. {reason}",
        request=request,
    )
    messages.success(request, "Donation cancelled and all affected users were notified.")
    return redirect("donations:detail", pk=donation.pk)


# ---------------------------------------------------------------------------
# NGO browse, request, and history
# ---------------------------------------------------------------------------
@role_required(User.Role.NGO)
def browse_donations(request):
    expire_overdue_donations()
    form = DonationFilterForm(request.GET or None)
    base = (
        FoodDonation.objects.available_for_request()
        .select_related("donor", "donor__donor_profile")
        .prefetch_related("requests")
    )

    if form.is_valid():
        q = (form.cleaned_data.get("q") or "").strip()
        category = form.cleaned_data.get("category")
        city = form.cleaned_data.get("city")
        unit = form.cleaned_data.get("unit")
        minimum = form.cleaned_data.get("min_quantity")
        maximum = form.cleaned_data.get("max_quantity")
        availability = form.cleaned_data.get("availability")
        sort = form.cleaned_data.get("sort") or "match"

        if q:
            base = base.filter(
                Q(food_name__icontains=q)
                | Q(description__icontains=q)
                | Q(pickup_city__icontains=q)
                | Q(donor__username__icontains=q)
                | Q(donor__donor_profile__organization_name__icontains=q)
            )
        if category:
            base = base.filter(category=category)
        if city:
            base = base.filter(pickup_city=city)
        if unit:
            base = base.filter(unit=unit)
        if minimum is not None:
            base = base.filter(quantity__gte=minimum)
        if maximum is not None:
            base = base.filter(quantity__lte=maximum)
        if availability == "expiring_6":
            base = base.filter(expires_at__lte=timezone.now() + timedelta(hours=6))
        elif availability == "expiring_24":
            base = base.filter(expires_at__lte=timezone.now() + timedelta(hours=24))
        elif availability == "expiring_48":
            base = base.filter(expires_at__lte=timezone.now() + timedelta(hours=48))
    else:
        sort = "match"

    matches = rank_donations_for_ngo(base, request.user)
    if sort == "newest":
        matches.sort(key=lambda result: result.donation.created_at, reverse=True)
    elif sort == "expiry":
        matches.sort(key=lambda result: result.donation.expires_at)
    elif sort == "quantity":
        matches.sort(key=lambda result: result.donation.quantity, reverse=True)

    paginator = Paginator(matches, 9)
    page_obj = paginator.get_page(request.GET.get("page"))
    profile = request.user.ngo_profile
    context = {
        "page_title": "Find Food",
        "active_nav": "browse",
        "form": form,
        "page_obj": page_obj,
        "total_matches": len(matches),
        "profile": profile,
        "verified": profile.verified,
        "high_matches": sum(1 for match in matches if match.level == "High Match"),
    }
    return render(request, "donations/browse.html", context)


@role_required(User.Role.NGO)
@require_POST
def submit_request(request, pk):
    expire_overdue_donations()
    donation = _get_donation(pk)
    if not can_view_donation(request.user, donation):
        raise PermissionDenied("You do not have access to this donation.")
    if not request.user.ngo_profile.verified:
        messages.error(request, "Your NGO must be verified before requesting food.")
        return redirect("donations:detail", pk=donation.pk)

    form = DonationRequestForm(request.POST, donation=donation)
    if form.is_valid():
        try:
            donation_request = create_donation_request(
                donation.pk,
                request.user,
                form.cleaned_data["quantity"],
                form.cleaned_data.get("message", ""),
            )
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
            return redirect("donations:detail", pk=donation.pk)

        log_audit(
            actor=request.user,
            action="donation_requested",
            obj=donation_request,
            description=f"Requested {donation_request.quantity} of “{donation.food_name}”.",
            request=request,
        )
        messages.success(request, "Request submitted. The donor has been notified.")
        return redirect("donations:detail", pk=donation.pk)

    messages.error(request, "Please correct the request form.")
    context = _detail_context(request, donation, request_form=form)
    return render(request, "donations/detail.html", context)


@login_required
@require_POST
def accept_donation_request(request, pk, request_id):
    donation = _get_donation(pk)
    if donation.donor_id != request.user.pk and not request.user.is_staff:
        raise PermissionDenied("Only the donor can accept requests.")
    try:
        donation_request = accept_request(request_id, request.user)
    except (ValidationError, DonationRequest.DoesNotExist) as exc:
        message = exc.messages[0] if isinstance(exc, ValidationError) else "Request not found."
        messages.error(request, message)
        return redirect("donations:detail", pk=donation.pk)

    log_audit(
        actor=request.user,
        action="request_accepted",
        obj=donation_request,
        description=f"Accepted request from {donation_request.ngo.display_name}.",
        request=request,
    )
    messages.success(request, "Request accepted. Other pending NGOs were notified.")
    return redirect("donations:detail", pk=donation.pk)


@login_required
@require_POST
def reject_donation_request(request, pk, request_id):
    donation = _get_donation(pk)
    if donation.donor_id != request.user.pk and not request.user.is_staff:
        raise PermissionDenied("Only the donor can reject requests.")
    try:
        donation_request = reject_request(
            request_id, request.user, request.POST.get("reason", "")
        )
    except (ValidationError, DonationRequest.DoesNotExist) as exc:
        message = exc.messages[0] if isinstance(exc, ValidationError) else "Request not found."
        messages.error(request, message)
        return redirect("donations:detail", pk=donation.pk)

    log_audit(
        actor=request.user,
        action="request_rejected",
        obj=donation_request,
        description=f"Rejected request from {donation_request.ngo.display_name}.",
        request=request,
    )
    messages.success(request, "Request rejected and the NGO was notified.")
    return redirect("donations:detail", pk=donation.pk)


@role_required(User.Role.NGO)
@require_POST
def cancel_donation_request(request, pk, request_id):
    donation = _get_donation(pk)
    try:
        donation_request = cancel_request_by_ngo(request_id, request.user)
    except (ValidationError, DonationRequest.DoesNotExist) as exc:
        message = exc.messages[0] if isinstance(exc, ValidationError) else "Request not found."
        messages.error(request, message)
        return redirect("donations:detail", pk=donation.pk)

    log_audit(
        actor=request.user,
        action="request_cancelled",
        obj=donation_request,
        description=f"NGO cancelled request for “{donation.food_name}”.",
        request=request,
    )
    messages.success(request, "Your request was cancelled.")
    return redirect("donations:detail", pk=donation.pk)


@login_required
@require_POST
def confirm_receipt(request, pk):
    donation = _get_donation(pk)
    try:
        complete_donation(donation.pk, request.user)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect("donations:detail", pk=donation.pk)

    log_audit(
        actor=request.user,
        action="donation_completed",
        obj=donation,
        description=f"Confirm receipt of “{donation.food_name}”.",
        request=request,
    )
    messages.success(request, "Receipt confirmed. This donation is now completed.")
    return redirect("donations:detail", pk=donation.pk)


@role_required(User.Role.NGO)
def ngo_requests(request):
    expire_overdue_donations()
    queryset = (
        request.user.donation_requests.select_related(
            "donation", "donation__donor", "donation__assignment"
        )
        .order_by("-created_at")
    )
    status = request.GET.get("status", "")
    if status in dict(DonationRequest.Status.choices):
        queryset = queryset.filter(status=status)
    q = request.GET.get("q", "").strip()
    if q:
        queryset = queryset.filter(
            Q(donation__food_name__icontains=q) | Q(donation__pickup_city__icontains=q)
        )
    paginator = Paginator(queryset, 15)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "donations/ngo_requests.html",
        {
            "page_title": "My Requests",
            "active_nav": "requests",
            "requests": page_obj.object_list,
            "page_obj": page_obj,
            "status_filter": status,
            "q": q,
            "statuses": DonationRequest.Status.choices,
            "stats": ngo_impact(request.user),
        },
    )


@role_required(User.Role.DONOR, User.Role.NGO)
def history(request):
    user = request.user
    if user.role == User.Role.DONOR:
        donations = (
            user.donations.filter(
                status__in=[
                    FoodDonation.Status.COMPLETED,
                    FoodDonation.Status.EXPIRED,
                    FoodDonation.Status.CANCELLED,
                ]
            )
            .select_related("donor")
            .order_by("-updated_at")
        )
        stats = donor_impact(user)
        requests = DonationRequest.objects.none()
    else:
        requests = (
            user.donation_requests.filter(
                status__in=[
                    DonationRequest.Status.FULFILLED,
                    DonationRequest.Status.EXPIRED,
                    DonationRequest.Status.REJECTED,
                    DonationRequest.Status.CANCELLED,
                ]
            )
            .select_related("donation", "donation__donor")
            .order_by("-updated_at")
        )
        donations = FoodDonation.objects.none()
        stats = ngo_impact(user)
    return render(
        request,
        "donations/history.html",
        {
            "page_title": "History",
            "active_nav": "history",
            "donations": donations,
            "requests": requests,
            "stats": stats,
        },
    )


# ---------------------------------------------------------------------------
# Admin monitoring
# ---------------------------------------------------------------------------
@admin_required
def admin_donations(request):
    expire_overdue_donations()
    form = AdminDonationFilterForm(request.GET or None)
    queryset = FoodDonation.objects.select_related("donor")
    if form.is_valid():
        queryset = form.filter(queryset)
    paginator = Paginator(queryset.order_by("-created_at"), 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "admin_dashboard/donations.html",
        {
            "page_title": "Manage Donations",
            "active_nav": "donations",
            "form": form,
            "page_obj": page_obj,
        },
    )


@admin_required
def admin_requests(request):
    form = AdminRequestFilterForm(request.GET or None)
    queryset = DonationRequest.objects.select_related(
        "donation", "donation__donor", "ngo", "ngo__ngo_profile"
    )
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if status in dict(DonationRequest.Status.choices):
        queryset = queryset.filter(status=status)
    if q:
        queryset = queryset.filter(
            Q(donation__food_name__icontains=q)
            | Q(ngo__username__icontains=q)
            | Q(ngo__ngo_profile__organization_name__icontains=q)
        )
    paginator = Paginator(queryset.order_by("-created_at"), 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "admin_dashboard/requests.html",
        {
            "page_title": "Monitor Requests",
            "active_nav": "requests",
            "form": form,
            "page_obj": page_obj,
            "status_filter": status,
            "q": q,
        },
    )
