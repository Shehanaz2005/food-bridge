from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from donations.models import DonationRequest, FoodDonation
from food_bridge.test_utils import (
    make_admin,
    make_donation,
    make_request,
    make_user,
)
from tracking.models import AuditLog, DonationTracking
from tracking.services import (
    JOURNEY_STEPS,
    build_journey,
    log_audit,
    record_event,
    serialize_status,
)


class TrackingServiceTests(TestCase):
    def setUp(self):
        self.donor = make_user("track_donor")
        self.donation = make_donation(
            self.donor, status=FoodDonation.Status.PICKED_UP
        )
        for status in ["available", "requested", "accepted", "assigned", "picked_up"]:
            record_event(
                self.donation,
                status,
                title=f"Event {status}",
                description=f"Description for {status}",
                actor=self.donor,
            )

    def test_record_event_uses_default_title(self):
        donation = make_donation(self.donor, food_name="Default Event Food")
        event = record_event(donation, "available")
        self.assertEqual(event.title, "Donation created")

    def test_build_journey_marks_done_current_and_pending(self):
        journey = build_journey(self.donation)
        self.assertEqual([step["key"] for step in journey], [s["key"] for s in JOURNEY_STEPS])
        current = [step for step in journey if step["current"]]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["key"], "picked_up")
        self.assertTrue(all(step["done"] for step in journey[:4]))
        self.assertFalse(any(step["done"] for step in journey[5:]))
        self.assertIsNotNone(current[0]["event"])

    def test_cancelled_journey_highlights_furthest_event(self):
        donation = make_donation(
            self.donor,
            food_name="Cancelled Journey Food",
            status=FoodDonation.Status.CANCELLED,
        )
        for status in ["available", "requested", "cancelled"]:
            record_event(donation, status)
        journey = build_journey(donation)
        current = [step for step in journey if step["current"]]
        self.assertEqual(current[0]["key"], "requested")

    def test_serialize_status_contains_safe_fields(self):
        data = serialize_status(self.donation)
        self.assertEqual(data["id"], self.donation.pk)
        self.assertEqual(data["status"], FoodDonation.Status.PICKED_UP)
        self.assertIn("status_label", data)
        self.assertIn("expires_at", data)
        self.assertIn("server_time", data)

    def test_log_audit_records_model_and_object(self):
        entry = log_audit(
            actor=self.donor,
            action="test_action",
            obj=self.donation,
            description="A test audit entry.",
        )
        self.assertEqual(entry.actor, self.donor)
        self.assertEqual(entry.model_name, "FoodDonation")
        self.assertEqual(entry.object_id, str(self.donation.pk))
        self.assertEqual(entry.action, "test_action")


class StatusApiTests(TestCase):
    def setUp(self):
        self.donor = make_user("api_donor")
        self.other_donor = make_user("api_other")
        self.volunteer = make_user("api_vol", role=User.Role.VOLUNTEER)
        self.donation = make_donation(self.donor, status=FoodDonation.Status.AVAILABLE)

    def test_anonymous_user_is_redirected(self):
        response = self.client.get(
            reverse("tracking:status", args=[self.donation.pk])
        )
        self.assertEqual(response.status_code, 302)

    def test_unrelated_user_gets_403(self):
        self.client.force_login(self.other_donor)
        response = self.client.get(
            reverse("tracking:status", args=[self.donation.pk])
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "You do not have access to this donation.")

    def test_owner_receives_status_json(self):
        self.client.force_login(self.donor)
        response = self.client.get(
            reverse("tracking:status", args=[self.donation.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], FoodDonation.Status.AVAILABLE)
        self.assertIn("no-store", response["Cache-Control"])

    def test_assigned_volunteer_receives_status(self):
        from food_bridge.test_utils import make_assignment

        make_assignment(
            self.donation, self.volunteer, status="accepted"
        )
        self.client.force_login(self.volunteer)
        response = self.client.get(
            reverse("tracking:status", args=[self.donation.pk])
        )
        self.assertEqual(response.status_code, 200)


class AuditViewTests(TestCase):
    def setUp(self):
        self.admin = make_admin("audit_admin")
        self.donor = make_user("audit_donor")

    def test_non_staff_cannot_open_audit(self):
        self.client.force_login(self.donor)
        response = self.client.get(reverse("admin_audit"))
        self.assertEqual(response.status_code, 403)

    def test_admin_can_filter_audit_by_action_and_search(self):
        log_audit(
            actor=self.donor,
            action="donation_created",
            description="Created a vegetable biryani donation.",
        )
        log_audit(
            actor=self.admin,
            action="ngo_verified",
            description="Verified an NGO.",
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin_audit"), {"action": "ngo_verified"})
        self.assertContains(response, "Verified an NGO")
        self.assertNotContains(response, "vegetable biryani")

        response = self.client.get(reverse("admin_audit"), {"q": "biryani"})
        self.assertContains(response, "vegetable biryani")
        self.assertNotContains(response, "Verified an NGO")


class TimelineTests(TestCase):
    def setUp(self):
        self.donor = make_user("timeline_donor")
        self.donation = make_donation(self.donor)
        now = timezone.now()
        self.old = DonationTracking.objects.create(
            donation=self.donation,
            status="available",
            title="First event",
            created_at=now - timedelta(hours=2),
        )
        self.new = DonationTracking.objects.create(
            donation=self.donation,
            status="available",
            title="Latest event",
            created_at=now,
        )
        self.client.force_login(self.donor)

    def test_detail_timeline_is_latest_first(self):
        response = self.client.get(
            reverse("donations:detail", args=[self.donation.pk])
        )
        events = list(response.context["tracking_events"])
        self.assertEqual(events[0], self.new)
        self.assertEqual(events[-1], self.old)
        self.assertContains(response, "Latest event")
