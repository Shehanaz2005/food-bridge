from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import admin_required
from accounts.models import User
from notifications.models import Notification
from notifications.services import notify
from tracking.services import log_audit

from .forms import AdminIssueUpdateForm, IssueFilterForm, IssueReportForm
from .models import IssueReport


@login_required
def report_issue(request):
    if request.method == "POST":
        form = IssueReportForm(request.POST, user=request.user)
        if form.is_valid():
            issue = form.save(commit=False)
            issue.reporter = request.user
            issue.save()
            for staff in User.objects.filter(is_staff=True, is_active=True):
                notify(
                    staff,
                    "New issue reported",
                    f"{request.user.display_name} reported: {issue.subject}",
                    level=Notification.Level.WARNING,
                    url=reverse("support:admin_issues"),
                )
            log_audit(
                actor=request.user,
                action="issue_reported",
                obj=issue,
                description=f"Reported issue: {issue.subject}",
                request=request,
            )
            messages.success(request, "Your report has been submitted. Our team will review it.")
            return redirect("support:report_issue")
        messages.error(request, "Please correct the highlighted fields.")
    else:
        form = IssueReportForm(user=request.user)

    context = {
        "form": form,
        "page_title": "Report an Issue",
        "active_nav": "support",
        "my_issues": request.user.issues.all()[:5],
    }
    return render(request, "support/report_issue.html", context)


@admin_required
def admin_issues(request):
    form = IssueFilterForm(request.GET or None)
    queryset = IssueReport.objects.select_related("reporter", "related_donation", "resolved_by")
    if form.is_valid():
        status = form.cleaned_data.get("status")
        q = (form.cleaned_data.get("q") or "").strip()
        if status:
            queryset = queryset.filter(status=status)
        if q:
            queryset = queryset.filter(
                Q(subject__icontains=q)
                | Q(description__icontains=q)
                | Q(reporter__username__icontains=q)
            )
    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "admin_dashboard/issues.html",
        {
            "page_title": "Reported Issues",
            "active_nav": "issues",
            "form": form,
            "page_obj": page_obj,
            "statuses": IssueReport.Status.choices,
            "open_count": IssueReport.objects.filter(
                status__in=[IssueReport.Status.OPEN, IssueReport.Status.IN_REVIEW]
            ).count(),
        },
    )


@admin_required
@require_POST
def admin_issue_update(request, pk):
    issue = get_object_or_404(IssueReport.objects.select_related("reporter"), pk=pk)
    form = AdminIssueUpdateForm(request.POST, instance=issue)
    if form.is_valid():
        issue = form.save(commit=False)
        if issue.status in {IssueReport.Status.RESOLVED, IssueReport.Status.DISMISSED}:
            issue.resolved_by = request.user
            issue.resolved_at = timezone.now()
        else:
            issue.resolved_by = None
            issue.resolved_at = None
        issue.save()
        notify(
            issue.reporter,
            "Your issue report was updated",
            f"“{issue.subject}” is now marked as {issue.get_status_display()}.",
            level=Notification.Level.INFO,
            url=reverse("support:report_issue"),
        )
        log_audit(
            actor=request.user,
            action="issue_updated",
            obj=issue,
            description=f"Updated issue “{issue.subject}” to {issue.get_status_display()}.",
            request=request,
        )
        messages.success(request, "Issue updated and the reporter was notified.")
    else:
        messages.error(request, "Could not update that issue.")
    return redirect("support:admin_issues")
