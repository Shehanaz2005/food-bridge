"""Database-backed impact analytics used by public pages and dashboards."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from accounts.models import NGOProfile, VolunteerProfile
from donations.constants import CATEGORY_ICONS, FOOD_CATEGORY_CHOICES, FOOD_UNIT_CHOICES
from donations.models import DonationRequest, FoodDonation
from support.models import IssueReport

User = get_user_model()

DELIVERED_STATUSES = [FoodDonation.Status.DELIVERED, FoodDonation.Status.COMPLETED]
RESCUED_STATUSES = [FoodDonation.Status.COMPLETED]
UNIT_LABELS = dict(FOOD_UNIT_CHOICES)
CATEGORY_LABELS = dict(FOOD_CATEGORY_CHOICES)


@dataclass
class ImpactOverview:
    total_donations: int
    completed_deliveries: int
    delivered_quantity: list[dict]
    donated_quantity: list[dict]
    ngos_connected: int
    active_donors: int
    active_volunteers: int
    active_requests: int
    meals_rescued: int
    completed_donations: int


@dataclass
class MonthlyPoint:
    month: date
    label: str
    created: int
    completed: int


@dataclass
class CategoryPoint:
    code: str
    label: str
    total: int
    completed: int
    percentage: int = 0
    icon: str = "fa-utensils"


def quantity_breakdown(queryset) -> list[dict]:
    rows = (
        queryset.values("unit")
        .annotate(total=Sum("quantity"))
        .order_by("unit")
    )
    result = []
    for row in rows:
        total = row["total"] or 0
        formatted = f"{total:.2f}".rstrip("0").rstrip(".")
        result.append(
            {
                "unit": row["unit"],
                "label": UNIT_LABELS.get(row["unit"], row["unit"]),
                "total": total,
                "formatted": formatted,
            }
        )
    return result


def get_impact_overview() -> ImpactOverview:
    donations = FoodDonation.objects.all()
    rescued = donations.filter(status__in=RESCUED_STATUSES)
    delivered = donations.filter(status__in=DELIVERED_STATUSES)
    completed_count = rescued.count()
    meals = (
        rescued.filter(unit="meals").aggregate(total=Sum("quantity"))["total"] or 0
    )
    return ImpactOverview(
        total_donations=donations.count(),
        completed_deliveries=completed_count,
        delivered_quantity=quantity_breakdown(delivered),
        donated_quantity=quantity_breakdown(donations.exclude(status=FoodDonation.Status.CANCELLED)),
        ngos_connected=NGOProfile.objects.filter(
            verified=True, user__is_blocked=False
        ).count(),
        active_donors=User.objects.filter(
            role=User.Role.DONOR,
            is_blocked=False,
            donations__status__in=[
                FoodDonation.Status.AVAILABLE,
                FoodDonation.Status.REQUESTED,
                FoodDonation.Status.ACCEPTED,
                FoodDonation.Status.ASSIGNED,
                FoodDonation.Status.PICKED_UP,
                FoodDonation.Status.DELIVERED,
                FoodDonation.Status.COMPLETED,
            ],
        )
        .distinct()
        .count(),
        active_volunteers=VolunteerProfile.objects.filter(
            is_available=True, user__is_blocked=False
        ).count(),
        active_requests=DonationRequest.objects.filter(
            status__in=[DonationRequest.Status.PENDING, DonationRequest.Status.ACCEPTED]
        ).count(),
        meals_rescued=int(meals),
        completed_donations=completed_count,
    )


def get_category_breakdown() -> list[CategoryPoint]:
    rows = (
        FoodDonation.objects.values("category")
        .annotate(
            total=Count("id"),
            completed=Count("id", filter=Q(status=FoodDonation.Status.COMPLETED)),
        )
        .order_by("-total")
    )
    grouped = {row["category"]: row for row in rows}
    total_all = sum(row["total"] for row in rows) or 1

    points = []
    # Show configured categories in a stable order, including zeroes.
    for code, label in FOOD_CATEGORY_CHOICES:
        row = grouped.get(code, {"total": 0, "completed": 0})
        points.append(
            CategoryPoint(
                code=code,
                label=label,
                total=row["total"],
                completed=row["completed"],
                percentage=round((row["total"] / total_all) * 100),
                icon=CATEGORY_ICONS.get(code, "fa-utensils"),
            )
        )
    points.sort(key=lambda point: point.total, reverse=True)
    return points


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = (year * 12 + (month - 1)) + delta
    return index // 12, index % 12 + 1


def get_monthly_trends(months: int = 8) -> list[MonthlyPoint]:
    today = timezone.localdate()
    first_year, first_month = _shift_month(today.year, today.month, -(months - 1))
    start = date(first_year, first_month, 1)

    created_rows = (
        FoodDonation.objects.filter(created_at__date__gte=start)
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(total=Count("id"))
    )
    completed_rows = (
        FoodDonation.objects.filter(
            completed_at__isnull=False,
            completed_at__date__gte=start,
        )
        .annotate(month=TruncMonth("completed_at"))
        .values("month")
        .annotate(total=Count("id"))
    )
    created_map = {
        (row["month"].year, row["month"].month): row["total"] for row in created_rows
    }
    completed_map = {
        (row["month"].year, row["month"].month): row["total"] for row in completed_rows
    }

    points = []
    for offset in range(months):
        year, month = _shift_month(first_year, first_month, offset)
        points.append(
            MonthlyPoint(
                month=date(year, month, 1),
                label=date(year, month, 1).strftime("%b"),
                created=created_map.get((year, month), 0),
                completed=completed_map.get((year, month), 0),
            )
        )
    return points


def chart_scale(points: list[MonthlyPoint]) -> int:
    highest = max([max(point.created, point.completed) for point in points] + [1])
    return max(4, highest)


@dataclass
class AdminSnapshot:
    overview: ImpactOverview
    unverified_ngos: int
    pending_requests: int
    awaiting_assignment: int
    open_issues: int
    total_users: int
    blocked_users: int
    active_deliveries: int
    recent_audit: list = field(default_factory=list)


def get_admin_snapshot() -> AdminSnapshot:
    awaiting_assignment = (
        FoodDonation.objects.filter(status=FoodDonation.Status.ACCEPTED)
        .filter(requests__status=DonationRequest.Status.ACCEPTED)
        .distinct()
        .count()
    )
    from tracking.models import AuditLog

    return AdminSnapshot(
        overview=get_impact_overview(),
        unverified_ngos=NGOProfile.objects.filter(verified=False).count(),
        pending_requests=DonationRequest.objects.filter(
            status=DonationRequest.Status.PENDING
        ).count(),
        awaiting_assignment=awaiting_assignment,
        open_issues=IssueReport.objects.filter(
            status__in=[IssueReport.Status.OPEN, IssueReport.Status.IN_REVIEW]
        ).count(),
        total_users=User.objects.count(),
        blocked_users=User.objects.filter(is_blocked=True).count(),
        active_deliveries=FoodDonation.objects.filter(
            status__in=[FoodDonation.Status.ASSIGNED, FoodDonation.Status.PICKED_UP]
        ).count(),
        recent_audit=list(AuditLog.objects.select_related("actor")[:8]),
    )


def donor_impact(user) -> dict:
    donations = user.donations.all()
    completed = donations.filter(status=FoodDonation.Status.COMPLETED)
    return {
        "total": donations.count(),
        "active": donations.filter(
            status__in=[
                FoodDonation.Status.AVAILABLE,
                FoodDonation.Status.REQUESTED,
                FoodDonation.Status.ACCEPTED,
                FoodDonation.Status.ASSIGNED,
                FoodDonation.Status.PICKED_UP,
                FoodDonation.Status.DELIVERED,
            ]
        ).count(),
        "completed": completed.count(),
        "pending_requests": DonationRequest.objects.filter(
            donation__donor=user, status=DonationRequest.Status.PENDING
        ).count(),
        "quantity": quantity_breakdown(completed),
        "rescued_meals": int(
            completed.filter(unit="meals").aggregate(total=Sum("quantity"))["total"] or 0
        ),
    }


def ngo_impact(user) -> dict:
    requests = user.donation_requests.all()
    received = requests.filter(status=DonationRequest.Status.FULFILLED)
    donations = FoodDonation.objects.filter(requests__ngo=user).distinct()
    return {
        "requests": requests.count(),
        "pending": requests.filter(status=DonationRequest.Status.PENDING).count(),
        "accepted": requests.filter(status=DonationRequest.Status.ACCEPTED).count(),
        "received": received.count(),
        "quantity": quantity_breakdown(donations.filter(status=FoodDonation.Status.COMPLETED)),
        "meals_received": int(
            donations.filter(status=FoodDonation.Status.COMPLETED, unit="meals").aggregate(
                total=Sum("quantity")
            )["total"]
            or 0
        ),
    }


def volunteer_impact(user) -> dict:
    assignments = user.volunteer_assignments.all()
    return {
        "total": assignments.count(),
        "offered": assignments.filter(status="offered").count(),
        "active": assignments.filter(status__in=["accepted", "picked_up"]).count(),
        "completed": assignments.filter(status="completed").count(),
        "delivered_quantity": quantity_breakdown(
            FoodDonation.objects.filter(
                assignment__volunteer=user,
                status=FoodDonation.Status.COMPLETED,
            )
        ),
    }
