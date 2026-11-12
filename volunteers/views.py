from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import admin_required, role_required
from accounts.models import User
from analytics.services import volunteer_impact
from donations.matching import recommended_volunteers
from donations.models import FoodDonation
from donations.workflow import (
    assign_volunteer,
    mark_delivered,
    mark_picked_up,
    volunteer_accept_assignment,
    volunteer_decline_assignment,
)
from tracking.services import build_journey, log_audit

from .forms import AssignVolunteerForm
from .models import PickupAssignment


def _assignment(pk):
    return get_object_or_404(
        PickupAssignment.objects.select_related(
            "donation",
            "donation__donor",
            "donation__donor__donor_profile",
            "volunteer",
            "assigned_by",
        ),
        pk=pk,
    )


@role_required(User.Role.VOLUNTEER)
def assignment_list(request):
    assignments = request.user.volunteer_assignments.select_related(
        "donation", "donation__donor", "donation__donor__donor_profile"
    )
    status = request.GET.get("status", "")
    if status in dict(PickupAssignment.Status.choices):
        assignments = assignments.filter(status=status)
    context = {
        "page_title": "Pickup Assignments",
        "active_nav": "assignments",
        "assignments": assignments,
        "status_filter": status,
        "statuses": PickupAssignment.Status.choices,
        "stats": volunteer_impact(request.user),
    }
    return render(request, "volunteers/assignments.html", context)


@role_required(User.Role.VOLUNTEER)
def assignment_detail(request, pk):
    assignment = _assignment(pk)
    if assignment.volunteer_id != request.user.pk:
        raise PermissionDenied("This assignment belongs to another volunteer.")
    donation = assignment.donation
    ngo = donation.recipient_ngo
    context = {
        "page_title": "Pickup Details",
        "active_nav": "assignments",
        "assignment": assignment,
        "donation": donation,
        "ngo": ngo,
        "journey": build_journey(donation),
        "timeline": donation.tracking_events.select_related("actor").order_by(
            "-created_at", "-pk"
        )[:20],
    }
    return render(request, "volunteers/assignment_detail.html", context)


@role_required(User.Role.VOLUNTEER)
@require_POST
def accept_assignment(request, pk):
    assignment = _assignment(pk)
    try:
        volunteer_accept_assignment(assignment.pk, request.user)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect("volunteers:assignment_detail", pk=assignment.pk)

    log_audit(
        actor=request.user,
        action="assignment_accepted",
        obj=assignment,
        description=f"Accepted pickup for “{assignment.donation.food_name}”.",
        request=request,
    )
    messages.success(request, "Assignment accepted. Coordinate the pickup with the donor.")
    return redirect("volunteers:assignment_detail", pk=assignment.pk)


@role_required(User.Role.VOLUNTEER)
@require_POST
def decline_assignment(request, pk):
    assignment = _assignment(pk)
    try:
        volunteer_decline_assignment(
            assignment.pk, request.user, request.POST.get("reason", "")
        )
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect("volunteers:assignment_detail", pk=assignment.pk)

    log_audit(
        actor=request.user,
        action="assignment_declined",
        obj=assignment,
        description=f"Declined pickup for “{assignment.donation.food_name}”.",
        request=request,
    )
    messages.info(request, "Assignment declined. The Food Bridge team has been notified.")
    return redirect("volunteers:assignments")


@role_required(User.Role.VOLUNTEER)
@require_POST
def mark_pickup(request, pk):
    assignment = _assignment(pk)
    try:
        mark_picked_up(assignment.pk, request.user)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect("volunteers:assignment_detail", pk=assignment.pk)

    log_audit(
        actor=request.user,
        action="food_picked_up",
        obj=assignment,
        description=f"Picked up “{assignment.donation.food_name}”.",
        request=request,
    )
    messages.success(request, "Pickup recorded. Deliver the food to the NGO and update the status.")
    return redirect("volunteers:assignment_detail", pk=assignment.pk)


@role_required(User.Role.VOLUNTEER)
@require_POST
def mark_delivery(request, pk):
    assignment = _assignment(pk)
    try:
        mark_delivered(assignment.pk, request.user)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect("volunteers:assignment_detail", pk=assignment.pk)

    log_audit(
        actor=request.user,
        action="food_delivered",
        obj=assignment,
        description=f"Delivered “{assignment.donation.food_name}” to the NGO.",
        request=request,
    )
    messages.success(request, "Delivery recorded. The NGO will confirm receipt to complete the donation.")
    return redirect("volunteers:assignment_detail", pk=assignment.pk)


@role_required(User.Role.VOLUNTEER)
def volunteer_history(request):
    assignments = request.user.volunteer_assignments.select_related(
        "donation"
    ).filter(status__in=["completed", "declined", "cancelled"]).order_by("-updated_at")
    return render(
        request,
        "volunteers/history.html",
        {
            "page_title": "Volunteer History",
            "active_nav": "history",
            "assignments": assignments,
            "stats": volunteer_impact(request.user),
        },
    )


# ---------------------------------------------------------------------------
# Admin assignment tools
# ---------------------------------------------------------------------------
@admin_required
def admin_assign(request, donation_id):
    donation = get_object_or_404(
        FoodDonation.objects.select_related("donor"), pk=donation_id
    )
    profile = donation.donor.donor_profile
    assignment = getattr(donation, "assignment", None)
    if donation.status not in {FoodDonation.Status.ACCEPTED, FoodDonation.Status.ASSIGNED}:
        messages.error(request, "Volunteers can only be assigned after an NGO request is accepted.")
        return redirect("donations:detail", pk=donation.pk)

    if request.method == "POST":
        form = AssignVolunteerForm(request.POST, donation=donation)
        if form.is_valid():
            try:
                new_assignment = assign_volunteer(
                    donation.pk,
                    form.cleaned_data["volunteer"].user,
                    request.user,
                    form.cleaned_data.get("notes", ""),
                )
            except ValidationError as exc:
                messages.error(request, exc.messages[0])
            else:
                log_audit(
                    actor=request.user,
                    action="volunteer_assigned",
                    obj=new_assignment,
                    description=f"Assigned {new_assignment.volunteer.display_name} to “{donation.food_name}”.",
                    request=request,
                )
                messages.success(request, "Volunteer assigned and notified.")
                return redirect("donations:detail", pk=donation.pk)
        else:
            messages.error(request, "Select an available volunteer.")
    else:
        form = AssignVolunteerForm(donation=donation)

    context = {
        "page_title": "Assign Volunteer",
        "active_nav": "donations",
        "donation": donation,
        "donor_profile": profile,
        "assignment": assignment,
        "form": form,
        "recommended": recommended_volunteers(donation),
    }
    return render(request, "admin_dashboard/assign_volunteer.html", context)


@admin_required
@require_POST
def admin_auto_assign(request, donation_id):
    donation = get_object_or_404(FoodDonation.objects.select_related("donor"), pk=donation_id)
    candidates = recommended_volunteers(donation, limit=1)
    if not candidates:
        messages.error(request, "No available volunteers found. Ask a volunteer to update availability.")
        return redirect("admin_assign", donation_id=donation.pk)
    try:
        assignment = assign_volunteer(
            donation.pk,
            candidates[0].user,
            request.user,
            "Automatically assigned by the Food Bridge matching workflow.",
        )
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect("admin_assign", donation_id=donation.pk)

    log_audit(
        actor=request.user,
        action="volunteer_auto_assigned",
        obj=assignment,
        description=f"Auto-assigned {assignment.volunteer.display_name} to “{donation.food_name}”.",
        request=request,
    )
    messages.success(
        request,
        f"{assignment.volunteer.display_name} was auto-assigned and notified.",
    )
    return redirect("donations:detail", pk=donation.pk)


@admin_required
def admin_assignments(request):
    queryset = PickupAssignment.objects.select_related(
        "donation", "donation__donor", "volunteer", "assigned_by"
    )
    status = request.GET.get("status", "")
    if status in dict(PickupAssignment.Status.choices):
        queryset = queryset.filter(status=status)
    q = request.GET.get("q", "").strip()
    if q:
        queryset = queryset.filter(
            Q(donation__food_name__icontains=q)
            | Q(volunteer__username__icontains=q)
            | Q(volunteer__first_name__icontains=q)
            | Q(volunteer__last_name__icontains=q)
        )
    paginator = Paginator(queryset.order_by("-created_at"), 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "admin_dashboard/assignments.html",
        {
            "page_title": "Monitor Pickups",
            "active_nav": "assignments",
            "page_obj": page_obj,
            "status_filter": status,
            "q": q,
            "statuses": PickupAssignment.Status.choices,
        },
    )
