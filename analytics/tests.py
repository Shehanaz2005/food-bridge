from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from analytics.services import (
    chart_scale,
    get_admin_snapshot,
    get_category_breakdown,
    get_impact_overview,
    get_monthly_trends,
    quantity_breakdown,
)
from donations.constants import FOOD_CATEGORY_CHOICES
from donations.models import DonationRequest, FoodDonation
from food_bridge.test_utils import (
    make_admin,
    make_donation,
    make_request,
    make_user,
)


class ImpactOverviewTests(TestCase):
    def setUp(self):
        self.donor = make_user("impact_donor")
        self.ngo = make_user("impact_ngo", role=User.Role.NGO)
        self.volunteer = make_user("impact_vol", role=User.Role.VOLUNTEER)
        self.available = make_donation(
            self.donor,
            food_name="Available Meals",
            quantity=10,
            unit="meals",
            status=FoodDonation.Status.AVAILABLE,
        )
        self.delivered = make_donation(
            self.donor,
            food_name="Delivered Rice",
            quantity=20,
            unit="kg",
            status=FoodDonation.Status.DELIVERED,
        )
        self.completed = make_donation(
            self.donor,
            food_name="Completed Bread",
            quantity=5,
            unit="kg",
            status=FoodDonation.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        self.cancelled = make_donation(
            self.donor,
            food_name="Cancelled Food",
            quantity=99,
            unit="kg",
            status=FoodDonation.Status.CANCELLED,
        )

    def test_overview_uses_real_records(self):
        overview = get_impact_overview()
        self.assertEqual(overview.total_donations, 4)
        self.assertEqual(overview.completed_deliveries, 1)
        self.assertEqual(overview.active_donors, 1)
        self.assertEqual(overview.active_volunteers, 1)
        self.assertEqual(overview.ngos_connected, 1)
        self.assertEqual(overview.active_requests, 0)
        self.assertEqual(overview.completed_donations, 1)

    def test_quantity_breakdown_sums_by_unit(self):
        rows = quantity_breakdown(
            FoodDonation.objects.filter(
                status__in=[FoodDonation.Status.DELIVERED, FoodDonation.Status.COMPLETED]
            )
        )
        values = {row["unit"]: row for row in rows}
        self.assertEqual(values["kg"]["total"], 25)
        self.assertEqual(values["kg"]["formatted"], "25")
        self.assertEqual(values["kg"]["label"], "Kilograms (kg)")

    def test_delivered_and_donated_quantities_exclude_cancelled(self):
        overview = get_impact_overview()
        delivered_units = {row["unit"]: row["total"] for row in overview.delivered_quantity}
        donated_units = {row["unit"]: row["total"] for row in overview.donated_quantity}
        self.assertEqual(delivered_units["kg"], 25)
        self.assertEqual(donated_units["kg"], 25)
        self.assertNotIn(99, donated_units.values())

    def test_active_requests_count_pending_and_accepted(self):
        request = make_request(self.available, self.ngo)
        make_request(
            self.delivered,
            make_user("impact_ngo_two", role=User.Role.NGO),
            status=DonationRequest.Status.ACCEPTED,
        )
        overview = get_impact_overview()
        self.assertEqual(overview.active_requests, 2)


class AnalyticsServiceTests(TestCase):
    def setUp(self):
        self.donor = make_user("stats_donor")

    def test_category_breakdown_includes_all_categories_and_icons(self):
        make_donation(self.donor, category="bakery", food_name="Bread Stats")
        make_donation(self.donor, category="bakery", food_name="Bread Stats 2")
        points = get_category_breakdown()
        self.assertEqual(len(points), len(FOOD_CATEGORY_CHOICES))
        bakery = next(point for point in points if point.code == "bakery")
        self.assertEqual(bakery.total, 2)
        self.assertEqual(bakery.icon, "fa-bread-slice")
        self.assertGreater(bakery.percentage, 0)

    def test_monthly_trends_have_expected_shape(self):
        points = get_monthly_trends(6)
        self.assertEqual(len(points), 6)
        self.assertEqual(points[-1].month.month, timezone.localdate().month)
        self.assertTrue(all(point.label for point in points))

    def test_monthly_trends_count_created_and_completed(self):
        donation = make_donation(
            self.donor,
            food_name="Trend Food",
            status=FoodDonation.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        FoodDonation.objects.filter(pk=donation.pk).update(created_at=timezone.now())
        points = get_monthly_trends(3)
        current = points[-1]
        self.assertGreaterEqual(current.created, 1)
        self.assertGreaterEqual(current.completed, 1)

    def test_chart_scale_has_minimum(self):
        self.assertEqual(chart_scale([]), 4)
        points = get_monthly_trends(2)
        self.assertGreaterEqual(chart_scale(points), 4)

    def test_admin_snapshot_counts_workflow_state(self):
        ngo = make_user("snapshot_ngo", role=User.Role.NGO)
        accepted = make_donation(
            self.donor, food_name="Awaiting Volunteer", status=FoodDonation.Status.ACCEPTED
        )
        make_request(accepted, ngo, status=DonationRequest.Status.ACCEPTED)
        snapshot = get_admin_snapshot()
        self.assertGreaterEqual(snapshot.pending_requests, 0)
        self.assertGreaterEqual(snapshot.awaiting_assignment, 1)
        self.assertGreaterEqual(snapshot.total_users, 2)
        self.assertEqual(snapshot.blocked_users, 0)


class AnalyticsViewTests(TestCase):
    def setUp(self):
        self.admin = make_admin("analytics_admin")
        self.donor = make_user("analytics_donor")
        self.donation = make_donation(
            self.donor,
            food_name="Public Hero Food",
            status=FoodDonation.Status.AVAILABLE,
        )

    def test_home_page_renders_live_donation(self):
        response = self.client.get(reverse("analytics:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Share Food,")
        self.assertContains(response, "Spread Hope.")
        self.assertContains(response, "Public Hero Food")
        self.assertContains(response, str(get_impact_overview().total_donations))

    def test_public_impact_page_renders(self):
        response = self.client.get(reverse("analytics:impact"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Live impact dashboard")
        self.assertContains(response, "Donations by category")

    def test_legal_pages_render(self):
        for name in ["food_safety", "privacy", "terms"]:
            with self.subTest(name=name):
                response = self.client.get(reverse(f"analytics:{name}"))
                self.assertEqual(response.status_code, 200)

    def test_non_admin_cannot_open_admin_analytics(self):
        self.client.force_login(self.donor)
        response = self.client.get(reverse("analytics:admin_analytics"))
        self.assertEqual(response.status_code, 403)

    def test_admin_analytics_renders_top_partners(self):
        ngo = make_user("analytics_ngo", role=User.Role.NGO)
        completed = make_donation(
            self.donor,
            food_name="Top Donor Food",
            status=FoodDonation.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        make_request(completed, ngo, status=DonationRequest.Status.FULFILLED)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("analytics:admin_analytics"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Top donor partners")
        self.assertContains(response, "Top NGO partners")
        self.assertContains(response, self.donor.display_name)
        self.assertContains(response, ngo.display_name)
