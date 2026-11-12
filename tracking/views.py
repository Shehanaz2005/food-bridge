from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache

from accounts.decorators import admin_required
from donations.models import FoodDonation
from donations.permissions import can_view_donation

from .models import AuditLog
from .services import serialize_status


@login_required
@never_cache
def donation_status(request, pk):
    donation = get_object_or_404(FoodDonation, pk=pk)
    if not can_view_donation(request.user, donation):
        return JsonResponse({"error": "You do not have access to this donation."}, status=403)
    response = JsonResponse(serialize_status(donation))
    response["Cache-Control"] = "no-store"
    return response


@admin_required
def admin_audit(request):
    queryset = AuditLog.objects.select_related("actor")
    q = request.GET.get("q", "").strip()
    action = request.GET.get("action", "").strip()
    if q:
        queryset = queryset.filter(
            Q(description__icontains=q)
            | Q(actor__username__icontains=q)
            | Q(model_name__icontains=q)
        )
    if action:
        queryset = queryset.filter(action=action)
    actions = (
        AuditLog.objects.values_list("action", flat=True)
        .distinct()
        .order_by("action")
    )
    paginator = Paginator(queryset, 30)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "admin_dashboard/audit.html",
        {
            "page_title": "System Activity",
            "active_nav": "audit",
            "page_obj": page_obj,
            "q": q,
            "action_filter": action,
            "actions": actions,
        },
    )
