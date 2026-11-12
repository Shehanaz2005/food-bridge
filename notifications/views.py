from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import Notification


@login_required
def notification_list(request):
    queryset = request.user.notifications.all()
    unread_only = request.GET.get("unread") == "1"
    if unread_only:
        queryset = queryset.filter(is_read=False)
    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "notifications/list.html",
        {
            "page_title": "Notifications",
            "active_nav": "notifications",
            "page_obj": page_obj,
            "unread_only": unread_only,
            "unread_count": request.user.notifications.filter(is_read=False).count(),
        },
    )


@login_required
@require_POST
def mark_read(request, pk):
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])
    target = notification.url
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(target)
    return redirect("notifications:list")


@login_required
@require_POST
def mark_all_read(request):
    updated = request.user.notifications.filter(is_read=False).update(is_read=True)
    from django.contrib import messages

    messages.success(request, f"Marked {updated} notification(s) as read.")
    return redirect("notifications:list")
