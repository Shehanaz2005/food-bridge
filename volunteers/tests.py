from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from donations.matching import recommended_volunteers
from donations.models import DonationRequest, FoodDonation
from donations.workflow import (
    assign_volunteer,
    mark_delivered,
    mark_picked_up,
    volunteer_accept_assignment,
    volunteer_decline_assignment,
)
from food_bridge.test_utils import (
    make_admin,
    make_assignment,
    make_donation,
    make_request,
    make_user,
)
from notifications.models import Notification
from tracking.models import DonationTracking
from volunteers.models import PickupAssignment


class VolunteerAssignmentTests(TestCase):
    def setUp(self):
        self.donor = make_user("vol_donor")
        self.ngo = make_user("vol_ngo", role=User.Role.NGO)
        self.volunteer = make_user("vol_owner", role=User.Role.VOLUNTEER, city="Mumbai")
        self.other_volunteer = make_user(
            "vol_other", role=User.Role.VOLUNTEER, city="Pune"
        )
        self.donation = make_donation(
            self.donor, status=FoodDonation.Status.ASSIGNED
        )
        make_request(self.donation, self.ngo, status=DonationRequest.Status.ACCEPTED)
        self.assignment = make_assignment(self.donation, self.volunteer)

    def test_assignment_list_only_shows_own_assignments(self):
        other_donation = make_donation(
            self.donor, food_name="Other Volunteer Food", status=FoodDonation.Status.ASSIGNED
        )
        make_assignment(other_donation, self.other_volunteer)
        self.client.force_login(self.volunteer)
        response = self.client.get(reverse("volunteers:assignments"))
        self.assertContains(response, self.donation.food_name)
        self.assertNotContains(response, "Other Volunteer Food")

    def test_assignment_detail_owner_only(self):
        self.client.force_login(self.other_volunteer)
        response = self.client.get(
            reverse("volunteers:assignment_detail", args=[self.assignment.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_volunteer_can_accept_assignment(self):
        self.client.force_login(self.volunteer)
        response = self.client.post(
            reverse("volunteers:accept", args=[self.assignment.pk])
        )
        self.assertRedirects(
            response,
            reverse("volunteers:assignment_detail", args=[self.assignment.pk]),
        )
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, PickupAssignment.Status.ACCEPTED)
        self.assertIsNotNone(self.assignment.accepted_at)
        self.assertTrue(
            DonationTracking.objects.filter(
                donation=self.donation, title="Volunteer accepted pickup"
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.donor, title__icontains="accepted your pickup"
            ).exists()
        )

    def test_only_owner_can_accept_assignment(self):
        with self.assertRaisesMessage(ValidationError, "not yours"):
            volunteer_accept_assignment(self.assignment.pk, self.other_volunteer)

    def test_accept_requires_offered_status(self):
        self.assignment.status = PickupAssignment.Status.ACCEPTED
        self.assignment.save(update_fields=["status"])
        with self.assertRaisesMessage(ValidationError, "no longer be accepted"):
            volunteer_accept_assignment(self.assignment.pk, self.volunteer)

    def test_decline_releases_donation_and_notifies_team(self):
        admin = make_admin("decline_admin")
        self.assignment.assigned_by = admin
        self.assignment.save(update_fields=["assigned_by"])
        self.client.force_login(self.volunteer)
        response = self.client.post(
            reverse("volunteers:decline", args=[self.assignment.pk]),
            {"reason": "Called into work"},
        )
        self.assertRedirects(response, reverse("volunteers:assignments"))
        self.assignment.refresh_from_db()
        self.donation.refresh_from_db()
        self.assertEqual(self.assignment.status, PickupAssignment.Status.DECLINED)
        self.assertIn("Called into work", self.assignment.notes)
        self.assertEqual(self.donation.status, FoodDonation.Status.ACCEPTED)
        self.assertTrue(
            Notification.objects.filter(
                user=admin, title__icontains="declined"
            ).exists()
        )

    def test_pickup_requires_accepted_assignment(self):
        with self.assertRaisesMessage(ValidationError, "Accept the assignment"):
            mark_picked_up(self.assignment.pk, self.volunteer)

    def test_volunteer_marks_pickup(self):
        volunteer_accept_assignment(self.assignment.pk, self.volunteer)
        self.client.force_login(self.volunteer)
        response = self.client.post(
            reverse("volunteers:pickup", args=[self.assignment.pk])
        )
        self.assertRedirects(
            response,
            reverse("volunteers:assignment_detail", args=[self.assignment.pk]),
        )
        self.assignment.refresh_from_db()
        self.donation.refresh_from_db()
        self.assertEqual(self.assignment.status, PickupAssignment.Status.PICKED_UP)
        self.assertEqual(self.donation.status, FoodDonation.Status.PICKED_UP)
        self.assertTrue(
            Notification.objects.filter(
                user=self.ngo, title__icontains="on the way"
            ).exists()
        )

    def test_expired_food_cannot_be_picked_up(self):
        volunteer_accept_assignment(self.assignment.pk, self.volunteer)
        self.donation.expires_at = timezone.now() - timedelta(minutes=1)
        self.donation.save(update_fields=["expires_at"])
        with self.assertRaisesMessage(ValidationError, "Expired food"):
            mark_picked_up(self.assignment.pk, self.volunteer)

    def test_delivery_requires_pickup(self):
        volunteer_accept_assignment(self.assignment.pk, self.volunteer)
        with self.assertRaisesMessage(ValidationError, "Mark the food as picked up"):
            mark_delivered(self.assignment.pk, self.volunteer)

    def test_volunteer_marks_delivery(self):
        volunteer_accept_assignment(self.assignment.pk, self.volunteer)
        mark_picked_up(self.assignment.pk, self.volunteer)
        mark_delivered(self.assignment.pk, self.volunteer)
        self.assignment.refresh_from_db()
        self.donation.refresh_from_db()
        self.assertEqual(self.assignment.status, PickupAssignment.Status.DELIVERED)
        self.assertEqual(self.donation.status, FoodDonation.Status.DELIVERED)
        self.assertIsNotNone(self.assignment.delivered_at)
        self.assertTrue(
            Notification.objects.filter(
                user=self.ngo, title__icontains="confirm receipt"
            ).exists()
        )

    def test_wrong_volunteer_cannot_mark_pickup(self):
        volunteer_accept_assignment(self.assignment.pk, self.volunteer)
        with self.assertRaisesMessage(ValidationError, "not yours"):
            mark_picked_up(self.assignment.pk, self.other_volunteer)

    def test_history_only_contains_finished_assignments(self):
        completed = make_donation(
            self.donor,
            food_name="Completed History Food",
            status=FoodDonation.Status.COMPLETED,
        )
        make_assignment(
            completed,
            self.volunteer,
            status=PickupAssignment.Status.COMPLETED,
        )
        self.client.force_login(self.volunteer)
        response = self.client.get(reverse("volunteers:history"))
        self.assertContains(response, "Completed History Food")
        self.assertNotContains(response, self.donation.food_name)


class AdminAssignmentTests(TestCase):
    def setUp(self):
        self.admin = make_admin("assign_admin")
        self.donor = make_user("assign_donor")
        self.ngo = make_user("assign_ngo", role=User.Role.NGO)
        self.volunteer = make_user(
            "assign_vol", role=User.Role.VOLUNTEER, city="Mumbai"
        )
        self.donation = make_donation(
            self.donor, status=FoodDonation.Status.ACCEPTED
        )
        make_request(self.donation, self.ngo, status=DonationRequest.Status.ACCEPTED)

    def test_admin_assigns_volunteer(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin_assign", args=[self.donation.pk]),
            {"volunteer": self.volunteer.volunteer_profile.pk, "notes": "Back gate"},
        )
        self.assertRedirects(response, reverse("donations:detail", args=[self.donation.pk]))
        self.donation.refresh_from_db()
        assignment = PickupAssignment.objects.get(donation=self.donation)
        self.assertEqual(self.donation.status, FoodDonation.Status.ASSIGNED)
        self.assertEqual(assignment.volunteer, self.volunteer)
        self.assertEqual(assignment.status, PickupAssignment.Status.OFFERED)
        self.assertTrue(
            Notification.objects.filter(
                user=self.volunteer, title__icontains="assignment"
            ).exists()
        )

    def test_unavailable_volunteer_is_not_offered(self):
        self.volunteer.volunteer_profile.is_available = False
        self.volunteer.volunteer_profile.save(update_fields=["is_available"])
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin_assign", args=[self.donation.pk]),
            {"volunteer": self.volunteer.volunteer_profile.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PickupAssignment.objects.filter(donation=self.donation).exists())

    def test_auto_assign_picks_available_volunteer(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin_auto_assign", args=[self.donation.pk])
        )
        self.assertRedirects(response, reverse("donations:detail", args=[self.donation.pk]))
        assignment = PickupAssignment.objects.get(donation=self.donation)
        self.assertEqual(assignment.volunteer, self.volunteer)
        self.assertTrue(
            DonationTracking.objects.filter(
                donation=self.donation, status=FoodDonation.Status.ASSIGNED
            ).exists()
        )

    def test_auto_assign_without_available_volunteers_shows_error(self):
        self.volunteer.volunteer_profile.is_available = False
        self.volunteer.volunteer_profile.save(update_fields=["is_available"])
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin_auto_assign", args=[self.donation.pk]), follow=True
        )
        self.assertContains(response, "No available volunteers")
        self.assertFalse(PickupAssignment.objects.filter(donation=self.donation).exists())

    def test_assign_requires_accepted_request(self):
        donation = make_donation(self.donor, status=FoodDonation.Status.AVAILABLE)
        with self.assertRaisesMessage(ValidationError, "only be assigned"):
            assign_volunteer(donation.pk, self.volunteer, self.admin)

    def test_cannot_assign_unavailable_volunteer_directly(self):
        self.volunteer.volunteer_profile.is_available = False
        self.volunteer.volunteer_profile.save(update_fields=["is_available"])
        with self.assertRaisesMessage(ValidationError, "currently unavailable"):
            assign_volunteer(self.donation.pk, self.volunteer, self.admin)

    def test_admin_assignments_page_filters(self):
        make_assignment(self.donation, self.volunteer)
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("admin_assignments"), {"status": "offered"}
        )
        self.assertContains(response, self.donation.food_name)
        self.assertContains(response, self.volunteer.display_name)

    def test_non_admin_cannot_open_assignment_tools(self):
        self.client.force_login(self.volunteer)
        self.assertEqual(
            self.client.get(reverse("admin_assignments")).status_code, 403
        )

    def test_recommended_volunteers_prefers_pickup_city(self):
        local = make_user("local_vol", role=User.Role.VOLUNTEER, city="Mumbai")
        remote = make_user("remote_vol", role=User.Role.VOLUNTEER, city="Delhi")
        ranked = recommended_volunteers(self.donation, limit=5)
        ranked_users = [profile.user for profile in ranked]
        self.assertIn(local, ranked_users)
        self.assertIn(remote, ranked_users)
        self.assertLess(ranked_users.index(local), ranked_users.index(remote))
        self.assertNotIn(
            self.volunteer.volunteer_profile,
            [p for p in ranked if p.user == self.volunteer and not p.is_available],
        )
