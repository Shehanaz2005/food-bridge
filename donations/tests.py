from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from donations.expiry import (
    expire_donation,
    expire_overdue_donations,
    send_expiry_warnings,
)
from donations.forms import DonationForm
from donations.matching import rank_donations_for_ngo, score_donation
from donations.models import DonationRequest, FoodDonation
from donations.workflow import (
    accept_request,
    assign_volunteer,
    cancel_donation,
    cancel_request_by_ngo,
    complete_donation,
    create_donation_request,
    reject_request,
)
from food_bridge.test_utils import (
    DEFAULT_PASSWORD,
    make_admin,
    make_assignment,
    make_donation,
    make_request,
    make_user,
)
from notifications.models import Notification
from tracking.models import AuditLog, DonationTracking
from volunteers.models import PickupAssignment


class DonationModelTests(TestCase):
    def setUp(self):
        self.donor = make_user("model_donor")
        self.ngo = make_user("model_ngo", role=User.Role.NGO)
        self.donation = make_donation(self.donor, quantity=20, unit="meals")

    def test_display_and_icon_properties(self):
        self.assertEqual(self.donation.quantity_display, "20 meals")
        self.assertEqual(self.donation.category_icon, "fa-bowl-food")
        self.assertEqual(self.donation.status_css, "success")
        self.assertEqual(
            self.donation.pickup_location,
            "10 Test Street, Mumbai",
        )

    def test_accepted_request_property_includes_fulfilled(self):
        request = make_request(
            self.donation, self.ngo, status=DonationRequest.Status.FULFILLED
        )
        self.assertEqual(self.donation.accepted_request, request)
        self.assertEqual(self.donation.recipient_ngo, self.ngo)

    def test_expired_donation_cannot_be_requested(self):
        self.donation.expires_at = timezone.now() - timedelta(minutes=1)
        self.donation.save(update_fields=["expires_at"])
        self.assertTrue(self.donation.is_expired)
        self.assertFalse(self.donation.can_be_requested)

    def test_unique_request_constraint(self):
        make_request(self.donation, self.ngo)
        with self.assertRaises(IntegrityError):
            make_request(self.donation, self.ngo)


class DonationCreationViewTests(TestCase):
    def setUp(self):
        self.donor = make_user("donor_one")
        self.other_donor = make_user("donor_two")
        self.client.force_login(self.donor)

    def _payload(self, **overrides):
        now = timezone.localtime()
        payload = {
            "food_name": "View Test Pulao",
            "category": "cooked_meal",
            "description": "Fresh test food.",
            "quantity": "12",
            "unit": "meals",
            "is_vegetarian": "on",
            "prepared_at": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
            "expires_at": (now + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M"),
            "pickup_address": "12 Test Street",
            "pickup_city": "Mumbai",
            "pickup_contact_name": "Donor One",
            "pickup_contact_phone": "+91 90000 00001",
            "handling_instructions": "Keep covered.",
        }
        payload.update(overrides)
        return payload

    def test_donor_creates_donation_with_event_and_audit(self):
        response = self.client.post(reverse("donations:create"), self._payload())
        donation = FoodDonation.objects.get(food_name="View Test Pulao")
        self.assertRedirects(response, reverse("donations:detail", args=[donation.pk]))
        self.assertEqual(donation.donor, self.donor)
        self.assertEqual(donation.status, FoodDonation.Status.AVAILABLE)
        self.assertTrue(
            DonationTracking.objects.filter(
                donation=donation, status=FoodDonation.Status.AVAILABLE
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="donation_created", actor=self.donor
            ).exists()
        )

    def test_past_expiry_is_rejected(self):
        now = timezone.localtime()
        response = self.client.post(
            reverse("donations:create"),
            self._payload(
                prepared_at=(now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M"),
                expires_at=(now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "must be in the future")
        self.assertFalse(FoodDonation.objects.filter(food_name="View Test Pulao").exists())

    def test_expiry_must_be_after_preparation(self):
        now = timezone.localtime()
        response = self.client.post(
            reverse("donations:create"),
            self._payload(
                prepared_at=(now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
                expires_at=(now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M"),
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "after preparation time")

    def test_donor_cannot_edit_someone_elses_donation(self):
        donation = make_donation(self.other_donor)
        response = self.client.get(reverse("donations:edit", args=[donation.pk]))
        self.assertEqual(response.status_code, 403)

    def test_donation_cannot_be_edited_after_acceptance(self):
        donation = make_donation(self.donor, status=FoodDonation.Status.ACCEPTED)
        response = self.client.get(reverse("donations:edit", args=[donation.pk]))
        self.assertRedirects(response, reverse("donations:detail", args=[donation.pk]))

    def test_ngo_cannot_create_donation(self):
        ngo = make_user("creator_ngo", role=User.Role.NGO)
        self.client.force_login(ngo)
        response = self.client.get(reverse("donations:create"))
        self.assertEqual(response.status_code, 403)


class DonationPermissionTests(TestCase):
    def setUp(self):
        self.donor = make_user("perm_donor")
        self.other_donor = make_user("perm_other")
        self.ngo = make_user("perm_ngo", role=User.Role.NGO)
        self.other_ngo = make_user("perm_other_ngo", role=User.Role.NGO)
        self.volunteer = make_user("perm_vol", role=User.Role.VOLUNTEER)
        self.donation = make_donation(self.donor, status=FoodDonation.Status.ASSIGNED)

    def test_donor_can_view_own_donation(self):
        self.client.force_login(self.donor)
        response = self.client.get(reverse("donations:detail", args=[self.donation.pk]))
        self.assertEqual(response.status_code, 200)

    def test_unrelated_donor_cannot_view(self):
        self.client.force_login(self.other_donor)
        response = self.client.get(reverse("donations:detail", args=[self.donation.pk]))
        self.assertEqual(response.status_code, 403)

    def test_verified_ngo_can_view_active_donation(self):
        self.client.force_login(self.ngo)
        response = self.client.get(reverse("donations:detail", args=[self.donation.pk]))
        self.assertEqual(response.status_code, 200)

    def test_unrelated_volunteer_cannot_view(self):
        self.client.force_login(self.volunteer)
        response = self.client.get(reverse("donations:detail", args=[self.donation.pk]))
        self.assertEqual(response.status_code, 403)

    def test_private_contact_is_hidden_until_accepted(self):
        self.client.force_login(self.other_ngo)
        response = self.client.get(reverse("donations:detail", args=[self.donation.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "shared once a request is accepted")
        self.assertNotContains(response, "10 Test Street")

    def test_private_contact_is_visible_to_recipient_ngo(self):
        make_request(
            self.donation, self.ngo, status=DonationRequest.Status.ACCEPTED
        )
        self.client.force_login(self.ngo)
        response = self.client.get(reverse("donations:detail", args=[self.donation.pk]))
        self.assertContains(response, "10 Test Street")

    def test_assigned_volunteer_can_view_donation(self):
        make_assignment(self.donation, self.volunteer)
        self.client.force_login(self.volunteer)
        response = self.client.get(reverse("donations:detail", args=[self.donation.pk]))
        self.assertEqual(response.status_code, 200)


class RequestWorkflowTests(TestCase):
    def setUp(self):
        self.donor = make_user("workflow_donor")
        self.ngo = make_user("workflow_ngo", role=User.Role.NGO)
        self.other_ngo = make_user("workflow_other_ngo", role=User.Role.NGO)
        self.donation = make_donation(self.donor, quantity=20, unit="meals")

    def test_verified_ngo_can_request_food(self):
        self.client.force_login(self.ngo)
        response = self.client.post(
            reverse("donations:request", args=[self.donation.pk]),
            {"quantity": "20", "message": "We will serve this tonight."},
        )
        self.assertRedirects(response, reverse("donations:detail", args=[self.donation.pk]))
        self.donation.refresh_from_db()
        self.assertEqual(self.donation.status, FoodDonation.Status.REQUESTED)
        request = DonationRequest.objects.get(donation=self.donation, ngo=self.ngo)
        self.assertEqual(request.status, DonationRequest.Status.PENDING)
        self.assertTrue(
            Notification.objects.filter(
                user=self.donor, title__icontains="request"
            ).exists()
        )

    def test_unverified_ngo_cannot_request_food(self):
        self.ngo.ngo_profile.verified = False
        self.ngo.ngo_profile.save(update_fields=["verified"])
        self.client.force_login(self.ngo)
        response = self.client.post(
            reverse("donations:request", args=[self.donation.pk]),
            {"quantity": "10"},
            follow=True,
        )
        self.assertContains(response, "must be verified")
        self.assertFalse(DonationRequest.objects.exists())

    def test_duplicate_requests_are_blocked(self):
        create_donation_request(self.donation.pk, self.ngo, 10, "First request")
        with self.assertRaisesMessage(
            ValidationError, "already submitted a request"
        ):
            create_donation_request(self.donation.pk, self.ngo, 10, "Second request")

    def test_request_quantity_cannot_exceed_donation(self):
        with self.assertRaisesMessage(
            ValidationError, "cannot exceed the donated quantity"
        ):
            create_donation_request(self.donation.pk, self.ngo, 25, "Too much")

    def test_expired_donation_cannot_be_requested(self):
        self.donation.expires_at = timezone.now() - timedelta(minutes=1)
        self.donation.save(update_fields=["expires_at"])
        with self.assertRaisesMessage(ValidationError, "expired or no longer available"):
            create_donation_request(self.donation.pk, self.ngo, 10)

    def test_accepting_request_allocates_donation_and_rejects_others(self):
        first = create_donation_request(self.donation.pk, self.ngo, 20, "First")
        second = create_donation_request(self.donation.pk, self.other_ngo, 10, "Second")
        accept_request(first.pk, self.donor)
        first.refresh_from_db()
        second.refresh_from_db()
        self.donation.refresh_from_db()
        self.assertEqual(first.status, DonationRequest.Status.ACCEPTED)
        self.assertEqual(second.status, DonationRequest.Status.REJECTED)
        self.assertEqual(self.donation.status, FoodDonation.Status.ACCEPTED)
        self.assertTrue(
            Notification.objects.filter(
                user=self.ngo, title__icontains="accepted"
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.other_ngo, title__icontains="another NGO"
            ).exists()
        )

    def test_only_donor_can_accept_request(self):
        request = create_donation_request(self.donation.pk, self.ngo, 20)
        with self.assertRaisesMessage(ValidationError, "Only the donor"):
            accept_request(request.pk, self.other_ngo)

    def test_rejecting_last_request_returns_donation_to_available(self):
        request = create_donation_request(self.donation.pk, self.ngo, 20)
        reject_request(request.pk, self.donor, "Unable to fulfil")
        request.refresh_from_db()
        self.donation.refresh_from_db()
        self.assertEqual(request.status, DonationRequest.Status.REJECTED)
        self.assertEqual(
            request.donor_note, "Unable to fulfil"
        )
        self.assertEqual(self.donation.status, FoodDonation.Status.AVAILABLE)
        self.assertTrue(
            Notification.objects.filter(
                user=self.ngo, title__icontains="declined"
            ).exists()
        )

    def test_ngo_can_cancel_own_request(self):
        request = create_donation_request(self.donation.pk, self.ngo, 20)
        cancel_request_by_ngo(request.pk, self.ngo)
        request.refresh_from_db()
        self.donation.refresh_from_db()
        self.assertEqual(request.status, DonationRequest.Status.CANCELLED)
        self.assertEqual(self.donation.status, FoodDonation.Status.AVAILABLE)
        self.assertTrue(
            Notification.objects.filter(user=self.donor).exists()
        )

    def test_donor_cancel_cancels_requests_and_assignment(self):
        volunteer = make_user("cancel_vol", role=User.Role.VOLUNTEER)
        request = create_donation_request(self.donation.pk, self.ngo, 20)
        accept_request(request.pk, self.donor)
        assignment = assign_volunteer(
            self.donation.pk, volunteer, make_admin("cancel_admin")
        )
        cancel_donation(self.donation.pk, self.donor, "Event finished early")
        self.donation.refresh_from_db()
        request.refresh_from_db()
        assignment.refresh_from_db()
        self.assertEqual(self.donation.status, FoodDonation.Status.CANCELLED)
        self.assertEqual(self.donation.cancelled_reason, "Event finished early")
        self.assertEqual(request.status, DonationRequest.Status.CANCELLED)
        self.assertEqual(assignment.status, PickupAssignment.Status.CANCELLED)
        self.assertTrue(
            Notification.objects.filter(
                user=volunteer, title__icontains="cancelled"
            ).exists()
        )

    def test_only_recipient_ngo_can_complete_delivery(self):
        request = make_request(
            self.donation, self.ngo, status=DonationRequest.Status.ACCEPTED
        )
        self.donation.status = FoodDonation.Status.DELIVERED
        self.donation.save(update_fields=["status"])
        with self.assertRaisesMessage(ValidationError, "Only the recipient NGO"):
            complete_donation(self.donation.pk, self.other_ngo)

    def test_recipient_ngo_completion_updates_all_records(self):
        volunteer = make_user("complete_vol", role=User.Role.VOLUNTEER)
        request = make_request(
            self.donation, self.ngo, status=DonationRequest.Status.ACCEPTED
        )
        assignment = make_assignment(
            self.donation, volunteer, status=PickupAssignment.Status.DELIVERED
        )
        self.donation.status = FoodDonation.Status.DELIVERED
        self.donation.save(update_fields=["status"])
        complete_donation(self.donation.pk, self.ngo)
        self.donation.refresh_from_db()
        request.refresh_from_db()
        assignment.refresh_from_db()
        self.assertEqual(self.donation.status, FoodDonation.Status.COMPLETED)
        self.assertIsNotNone(self.donation.completed_at)
        self.assertEqual(request.status, DonationRequest.Status.FULFILLED)
        self.assertEqual(assignment.status, PickupAssignment.Status.COMPLETED)
        self.assertIsNotNone(assignment.completed_at)
        self.assertTrue(
            Notification.objects.filter(
                user=self.donor, title__icontains="completed"
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=volunteer, title__icontains="Delivery completed"
            ).exists()
        )

    def test_confirm_receipt_view_requires_delivered_status(self):
        self.client.force_login(self.ngo)
        response = self.client.post(
            reverse("donations:confirm", args=[self.donation.pk]), follow=True
        )
        self.assertContains(response, "Only delivered donations can be completed")

    def test_browse_page_respects_category_filter(self):
        make_donation(
            self.donor,
            food_name="Bread Basket",
            category="bakery",
            quantity=5,
            unit="kg",
        )
        self.client.force_login(self.ngo)
        response = self.client.get(reverse("donations:browse"), {"category": "bakery"})
        self.assertContains(response, "Bread Basket")
        self.assertNotContains(response, "Test Biryani")

    def test_donor_list_is_paginated(self):
        for index in range(14):
            make_donation(self.donor, food_name=f"Batch Donation {index}")
        self.client.force_login(self.donor)
        response = self.client.get(reverse("donations:list"))
        self.assertEqual(len(response.context["page_obj"].object_list), 12)
        self.assertEqual(response.context["page_obj"].paginator.count, 15)


class ExpiryTests(TestCase):
    def setUp(self):
        self.donor = make_user("expiry_donor")
        self.ngo = make_user("expiry_ngo", role=User.Role.NGO)
        self.volunteer = make_user("expiry_vol", role=User.Role.VOLUNTEER)

    def test_expire_donation_closes_requests_and_assignment(self):
        donation = make_donation(self.donor, status=FoodDonation.Status.ASSIGNED)
        request = make_request(
            donation, self.ngo, status=DonationRequest.Status.ACCEPTED
        )
        assignment = make_assignment(donation, self.volunteer)
        self.assertTrue(expire_donation(donation.pk))
        donation.refresh_from_db()
        request.refresh_from_db()
        assignment.refresh_from_db()
        self.assertEqual(donation.status, FoodDonation.Status.EXPIRED)
        self.assertEqual(request.status, DonationRequest.Status.EXPIRED)
        self.assertEqual(assignment.status, PickupAssignment.Status.CANCELLED)
        self.assertTrue(
            Notification.objects.filter(user=self.donor, level="danger").exists()
        )
        self.assertTrue(
            Notification.objects.filter(user=self.volunteer, level="danger").exists()
        )

    def test_expire_overdue_only_touches_overdue_active_donations(self):
        overdue = make_donation(
            self.donor,
            food_name="Overdue Food",
            expires_at=timezone.now() - timedelta(minutes=5),
        )
        future = make_donation(
            self.donor,
            food_name="Future Food",
            expires_at=timezone.now() + timedelta(hours=3),
        )
        picked_up = make_donation(
            self.donor,
            food_name="Picked Up Food",
            status=FoodDonation.Status.PICKED_UP,
            expires_at=timezone.now() - timedelta(minutes=5),
        )
        expired = expire_overdue_donations()
        overdue.refresh_from_db()
        future.refresh_from_db()
        picked_up.refresh_from_db()
        self.assertEqual(expired, 1)
        self.assertEqual(overdue.status, FoodDonation.Status.EXPIRED)
        self.assertEqual(future.status, FoodDonation.Status.AVAILABLE)
        self.assertEqual(picked_up.status, FoodDonation.Status.PICKED_UP)

    def test_management_command_expires_overdue_donation(self):
        donation = make_donation(
            self.donor, expires_at=timezone.now() - timedelta(minutes=1)
        )
        call_command("mark_expired_donations")
        donation.refresh_from_db()
        self.assertEqual(donation.status, FoodDonation.Status.EXPIRED)

    def test_expiry_warnings_are_deduplicated(self):
        donation = make_donation(
            self.donor, expires_at=timezone.now() + timedelta(hours=3)
        )
        make_request(donation, self.ngo)
        warned = send_expiry_warnings(hours=6)
        self.assertEqual(warned, 1)
        self.assertEqual(
            Notification.objects.filter(
                title="Food is approaching expiry"
            ).count(),
            2,
        )
        warned_again = send_expiry_warnings(hours=6)
        self.assertEqual(warned_again, 1)
        self.assertEqual(
            Notification.objects.filter(
                title="Food is approaching expiry"
            ).count(),
            2,
        )

    def test_expired_food_cannot_be_assigned_or_picked_up(self):
        donation = make_donation(
            self.donor,
            status=FoodDonation.Status.ACCEPTED,
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        make_request(donation, self.ngo, status=DonationRequest.Status.ACCEPTED)
        with self.assertRaisesMessage(ValidationError, "Expired food"):
            assign_volunteer(donation.pk, self.volunteer, make_admin("expiry_admin"))


class MatchingTests(TestCase):
    def setUp(self):
        self.donor = make_user("match_donor", city="Mumbai")
        self.ngo = make_user("match_ngo", role=User.Role.NGO, city="Mumbai")
        profile = self.ngo.ngo_profile
        profile.preferred_categories = ["cooked_meal"]
        profile.minimum_quantity = 10
        profile.minimum_unit = "meals"
        profile.service_area = "Mumbai"
        profile.save()

    def test_high_match_is_explainable(self):
        donation = make_donation(
            self.donor,
            quantity=20,
            unit="meals",
            expires_at=timezone.now() + timedelta(hours=2),
        )
        match = score_donation(donation, self.ngo)
        self.assertGreaterEqual(match.score, 75)
        self.assertEqual(match.level, "High Match")
        self.assertIn("Matches your preferred food category", " ".join(match.reasons))
        self.assertIn("Pickup is in your city", " ".join(match.reasons))
        self.assertIn("quantity you need", " ".join(match.reasons))
        self.assertIn("fast rescue", " ".join(match.reasons))

    def test_medium_match_threshold(self):
        donation = make_donation(
            self.donor,
            category="bakery",
            quantity=5,
            unit="kg",
            expires_at=timezone.now() + timedelta(hours=10),
        )
        match = score_donation(donation, self.ngo)
        self.assertGreaterEqual(match.score, 50)
        self.assertLess(match.score, 75)
        self.assertEqual(match.level, "Medium Match")
        self.assertIn("outside your usual preferences", " ".join(match.reasons))

    def test_low_match_threshold(self):
        far_ngo = make_user("far_ngo", role=User.Role.NGO, city="Delhi")
        profile = far_ngo.ngo_profile
        profile.preferred_categories = ["dairy"]
        profile.minimum_quantity = 100
        profile.minimum_unit = "kg"
        profile.service_area = "Delhi"
        profile.save()
        donation = make_donation(
            self.donor,
            category="cooked_meal",
            quantity=5,
            unit="meals",
            expires_at=timezone.now() + timedelta(days=7),
        )
        match = score_donation(donation, far_ngo)
        self.assertLess(match.score, 50)
        self.assertEqual(match.level, "Low Match")

    def test_ranking_excludes_expired_and_sorts_by_score(self):
        good = make_donation(
            self.donor,
            food_name="Good Match",
            quantity=20,
            unit="meals",
            expires_at=timezone.now() + timedelta(hours=2),
        )
        weak = make_donation(
            self.donor,
            food_name="Weak Match",
            category="bakery",
            quantity=2,
            unit="kg",
            expires_at=timezone.now() + timedelta(days=5),
        )
        expired = make_donation(
            self.donor,
            food_name="Expired Match",
            quantity=20,
            unit="meals",
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        matches = rank_donations_for_ngo([weak, good, expired], self.ngo)
        self.assertEqual([match.donation for match in matches], [good, weak])

    def test_ngo_without_preferences_gets_neutral_category_score(self):
        ngo = make_user("neutral_ngo", role=User.Role.NGO, city="Surat")
        donation = make_donation(self.donor, quantity=5, unit="kg")
        match = score_donation(donation, ngo)
        self.assertIn("no category preferences", " ".join(match.reasons))

    def test_admin_can_filter_donations(self):
        make_donation(self.donor, food_name="Admin Bakery", category="bakery")
        admin = make_admin("filter_admin")
        self.client.force_login(admin)
        response = self.client.get(
            reverse("admin_donations"), {"category": "bakery"}
        )
        self.assertContains(response, "Admin Bakery")
        self.assertNotContains(response, "Test Biryani")
