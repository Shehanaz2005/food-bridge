from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.shortcuts import render

from accounts.decorators import admin_required
from donations.expiry import expire_overdue_donations
from donations.models import DonationRequest, FoodDonation

from .services import (
    chart_scale,
    get_admin_snapshot,
    get_category_breakdown,
    get_impact_overview,
    get_monthly_trends,
)

User = get_user_model()

LEGAL_PAGES = {
    "food-safety": {
        "title": "Food safety policy",
        "lead": "Safe food comes first. These rules protect the people who receive every meal and the donors who share it.",
        "sections": [
            {
                "title": "What can be donated",
                "body": [
                    "Food must be freshly prepared, properly stored, and still within its safe consumption window. Every listing includes a preparation time and a best-before time.",
                    "Donors confirm that food has not been served, returned from a table, or handled in unsafe conditions. Raw and cooked food must be kept separate before pickup.",
                ],
            },
            {
                "title": "The expiry window",
                "body": [
                    "Food Bridge monitors every listing automatically. Once the best-before time passes, the donation is marked expired and can no longer be requested, assigned, picked up, or delivered.",
                    "Expired listings remain visible in history for accountability, but the platform blocks any further distribution activity.",
                ],
            },
            {
                "title": "Handling and transport",
                "body": [
                    "Donors provide handling instructions for each listing. Volunteers must follow those instructions and keep food covered and at a safe temperature during transport.",
                    "If a volunteer suspects that food is unsafe at pickup, they should decline the assignment and report the problem through the platform.",
                ],
            },
            {
                "title": "Receipt and accountability",
                "body": [
                    "The recipient NGO confirms receipt before a donation is marked completed. This keeps the impact record honest and gives both sides a clear completion point.",
                    "Every status change is recorded in the donation timeline and the platform audit trail.",
                ],
            },
        ],
    },
    "privacy": {
        "title": "Privacy policy",
        "lead": "We collect only what is needed to coordinate food rescues and keep the platform trustworthy.",
        "sections": [
            {
                "title": "Information we collect",
                "body": [
                    "Account information includes your name, email address, role, city, phone number, and profile details relevant to your role. Donors may add pickup contact details and food handling notes.",
                    "Workflow records include donations, requests, assignments, status events, notifications, and an audit trail of platform actions.",
                ],
            },
            {
                "title": "How information is used",
                "body": [
                    "Contact and pickup details are used to coordinate donations, requests, and deliveries. They are shared only with the people involved in an accepted rescue.",
                    "Aggregated impact figures contain no personal information and may be shown publicly on the impact page.",
                ],
            },
            {
                "title": "Who can see what",
                "body": [
                    "Exact pickup addresses and phone numbers are hidden from NGOs and volunteers until a request is accepted and delivery is being arranged.",
                    "Administrators can access account and workflow records for verification, safety, and dispute resolution. Access is logged in the audit trail.",
                ],
            },
            {
                "title": "Your choices",
                "body": [
                    "You can update your profile and password at any time. To request correction or removal of account data, contact hello@foodbridge.org from the email address on your account.",
                    "Some records may be retained where needed for food-safety accountability or legal obligations.",
                ],
            },
        ],
    },
    "terms": {
        "title": "Terms of use",
        "lead": "Food Bridge is a coordination platform. It helps people organise food rescues, but it does not prepare, inspect, or transport food itself.",
        "sections": [
            {
                "title": "Using the platform",
                "body": [
                    "Provide accurate information, use your own account, and choose the role that matches what you are actually doing. NGOs must be verified before requesting food.",
                    "Do not use Food Bridge for commercial resale, harassment, false listings, or any activity that could put recipients at risk.",
                ],
            },
            {
                "title": "Responsibilities",
                "body": [
                    "Donors are responsible for the safety, accuracy, and lawful handling of the food they list. NGOs are responsible for safe storage and distribution after receipt. Volunteers are responsible for following handling instructions during pickup and delivery.",
                    "Food Bridge may suspend or block accounts that break these rules, with the reason recorded in the audit trail.",
                ],
            },
            {
                "title": "Availability and limits",
                "body": [
                    "We work to keep the platform available and accurate, but it is provided without a guarantee of uninterrupted service. In an emergency, contact local food-safety or emergency services directly.",
                    "Food Bridge is not a party to any donation and does not provide legal, medical, or food-safety certification.",
                ],
            },
            {
                "title": "Changes",
                "body": [
                    "We may update these terms as the platform develops. Continued use after an update means you accept the current version.",
                    "Questions can be sent to hello@foodbridge.org.",
                ],
            },
        ],
    },
}


def _legal_page(request, slug):
    page = LEGAL_PAGES[slug]
    return render(
        request,
        "pages/legal.html",
        {
            "page_title": page["title"],
            "legal_title": page["title"],
            "legal_lead": page["lead"],
            "legal_sections": page["sections"],
        },
    )


def food_safety(request):
    return _legal_page(request, "food-safety")


def privacy(request):
    return _legal_page(request, "privacy")


def terms(request):
    return _legal_page(request, "terms")


def home(request):
    expire_overdue_donations()
    overview = get_impact_overview()
    latest_donations = (
        FoodDonation.objects.available_for_request()
        .select_related("donor", "donor__donor_profile")
        .order_by("-created_at")[:3]
    )
    context = {
        "overview": overview,
        "latest_donations": latest_donations,
        "hero_donation": latest_donations[0] if latest_donations else None,
    }
    return render(request, "home.html", context)


def impact(request):
    expire_overdue_donations()
    overview = get_impact_overview()
    categories = get_category_breakdown()
    trends = get_monthly_trends(8)
    context = {
        "overview": overview,
        "categories": categories,
        "trends": trends,
        "scale": chart_scale(trends),
        "page_title": "Our Impact",
    }
    return render(request, "impact.html", context)


@admin_required
def admin_analytics(request):
    snapshot = get_admin_snapshot()
    categories = get_category_breakdown()
    trends = get_monthly_trends(12)
    top_donors = (
        User.objects.filter(role=User.Role.DONOR, is_blocked=False)
        .annotate(
            completed=Count(
                "donations",
                filter=Q(donations__status=FoodDonation.Status.COMPLETED),
            ),
            total=Count("donations"),
        )
        .filter(completed__gt=0)
        .order_by("-completed")[:6]
    )
    top_ngos = (
        User.objects.filter(role=User.Role.NGO, is_blocked=False)
        .annotate(
            received=Count(
                "donation_requests",
                filter=Q(donation_requests__status=DonationRequest.Status.FULFILLED),
            )
        )
        .filter(received__gt=0)
        .order_by("-received")[:6]
    )
    context = {
        "page_title": "Impact Analytics",
        "active_nav": "analytics",
        "snapshot": snapshot,
        "overview": snapshot.overview,
        "categories": categories,
        "trends": trends,
        "scale": chart_scale(trends),
        "top_donors": top_donors,
        "top_ngos": top_ngos,
    }
    return render(request, "admin_dashboard/analytics.html", context)
