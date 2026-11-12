from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from accounts.forms import FoodBridgeLoginForm
from accounts.models import DonorProfile, NGOProfile, User
from food_bridge.test_utils import DEFAULT_PASSWORD, make_admin, make_user
from notifications.models import Notification
from tracking.models import AuditLog


class RegistrationTests(TestCase):
    def test_donor_registration_creates_profile_and_signs_in(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "role": User.Role.DONOR,
                "username": "new_donor",
                "first_name": "New",
                "last_name": "Donor",
                "email": "new_donor@example.com",
                "phone": "+91 90000 11111",
                "city": "Mumbai",
                "address": "1 New Street",
                "organization_name": "",
                "donor_type": "individual",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
                "terms": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="new_donor")
        self.assertEqual(user.role, User.Role.DONOR)
        self.assertTrue(user.check_password("StrongPass123!"))
        self.assertTrue(DonorProfile.objects.filter(user=user).exists())
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_ngo_registration_is_unverified(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "role": User.Role.NGO,
                "username": "new_ngo",
                "first_name": "New",
                "last_name": "NGO",
                "email": "new_ngo@example.com",
                "phone": "+91 90000 22222",
                "city": "Pune",
                "address": "2 NGO Road",
                "organization_name": "New NGO Foundation",
                "registration_number": "MH-2026-001",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
                "terms": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        profile = NGOProfile.objects.get(user__username="new_ngo")
        self.assertEqual(profile.organization_name, "New NGO Foundation")
        self.assertFalse(profile.verified)
        self.assertEqual(Notification.objects.filter(user__username="new_ngo").count(), 1)

    def test_duplicate_email_is_rejected(self):
        make_user("existing", email="taken@example.com")
        response = self.client.post(
            reverse("accounts:register"),
            {
                "role": User.Role.DONOR,
                "username": "another",
                "first_name": "Another",
                "last_name": "Person",
                "email": "TAKEN@example.com",
                "city": "Mumbai",
                "address": "3 Street",
                "donor_type": "individual",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
                "terms": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")
        self.assertFalse(User.objects.filter(username="another").exists())

    def test_terms_are_required(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "role": User.Role.DONOR,
                "username": "no_terms",
                "first_name": "No",
                "last_name": "Terms",
                "email": "no_terms@example.com",
                "city": "Mumbai",
                "address": "4 Street",
                "donor_type": "individual",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "accept the community guidelines")
        self.assertFalse(User.objects.filter(username="no_terms").exists())


class LoginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user("login_user", email="login@example.com")

    def tearDown(self):
        cache.clear()

    def test_login_with_username(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "login_user", "password": DEFAULT_PASSWORD},
        )
        self.assertRedirects(
            response,
            reverse("accounts:dashboard"),
            fetch_redirect_response=False,
        )

    def test_login_with_email(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "login@example.com", "password": DEFAULT_PASSWORD},
        )
        self.assertRedirects(
            response,
            reverse("accounts:dashboard"),
            fetch_redirect_response=False,
        )

    def test_blocked_account_cannot_sign_in(self):
        self.user.is_blocked = True
        self.user.blocked_reason = "Repeated policy violations"
        self.user.save(update_fields=["is_blocked", "blocked_reason"])
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "login_user", "password": DEFAULT_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "blocked")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_repeated_failures_trigger_lockout(self):
        for _ in range(5):
            self.client.post(
                reverse("accounts:login"),
                {"username": "login_user", "password": "WrongPassword123!"},
            )
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "login_user", "password": DEFAULT_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Too many failed sign-in attempts")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_form_rejects_locked_identifier(self):
        cache.set("login-failures:login_user", 5, timeout=900)
        form = FoodBridgeLoginForm(
            data={"username": "login_user", "password": DEFAULT_PASSWORD}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("Too many failed sign-in attempts", str(form.errors))


class RoleAccessTests(TestCase):
    def setUp(self):
        self.donor = make_user("donor_user")
        self.ngo = make_user("ngo_user", role=User.Role.NGO)
        self.volunteer = make_user("volunteer_user", role=User.Role.VOLUNTEER)
        self.admin = make_admin()

    def test_anonymous_users_are_redirected_to_login(self):
        response = self.client.get(reverse("accounts:donor_dashboard"))
        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('accounts:donor_dashboard')}",
        )

    def test_donor_cannot_open_ngo_dashboard(self):
        self.client.force_login(self.donor)
        response = self.client.get(reverse("accounts:ngo_dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_ngo_cannot_open_volunteer_dashboard(self):
        self.client.force_login(self.ngo)
        response = self.client.get(reverse("accounts:volunteer_dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_non_staff_cannot_open_admin_dashboard(self):
        self.client.force_login(self.donor)
        response = self.client.get(reverse("accounts:admin_dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_admin_can_open_operational_pages(self):
        self.client.force_login(self.admin)
        for url in [
            reverse("accounts:admin_dashboard"),
            reverse("accounts:admin_users"),
            reverse("admin_donations"),
            reverse("admin_requests"),
            reverse("admin_assignments"),
            reverse("admin_audit"),
            reverse("support:admin_issues"),
            reverse("analytics:admin_analytics"),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_blocked_user_session_is_terminated(self):
        self.client.force_login(self.donor)
        self.donor.is_blocked = True
        self.donor.save(update_fields=["is_blocked"])
        response = self.client.get(reverse("accounts:donor_dashboard"))
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertNotIn("_auth_user_id", self.client.session)


class AdminManagementTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.ngo = make_user("pending_ngo", role=User.Role.NGO)
        self.ngo.ngo_profile.verified = False
        self.ngo.ngo_profile.save(update_fields=["verified"])

    def test_admin_can_verify_ngo(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:verify_ngo", args=[self.ngo.pk]),
            {"next": reverse("accounts:admin_users")},
        )
        self.assertRedirects(response, reverse("accounts:admin_users"))
        self.ngo.ngo_profile.refresh_from_db()
        self.assertTrue(self.ngo.ngo_profile.verified)
        self.assertEqual(self.ngo.ngo_profile.verified_by, self.admin)
        self.assertTrue(
            Notification.objects.filter(
                user=self.ngo, title__icontains="verification"
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(action="ngo_verified", actor=self.admin).exists()
        )

    def test_admin_can_block_and_unblock_account(self):
        self.client.force_login(self.admin)
        url = reverse("accounts:block_user", args=[self.ngo.pk])
        self.client.post(url, {"reason": "Policy violation"})
        self.ngo.refresh_from_db()
        self.assertTrue(self.ngo.is_blocked)
        self.assertEqual(self.ngo.blocked_reason, "Policy violation")

        self.client.post(url, {})
        self.ngo.refresh_from_db()
        self.assertFalse(self.ngo.is_blocked)
        self.assertEqual(self.ngo.blocked_reason, "")
        self.assertTrue(
            AuditLog.objects.filter(action="account_unblocked").exists()
        )

    def test_admin_cannot_block_self_or_superuser(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:block_user", args=[self.admin.pk]),
            follow=True,
        )
        self.assertContains(response, "cannot block this account")
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.is_blocked)

    def test_user_filters_search_by_role_and_status(self):
        make_user("blocked_ngo", role=User.Role.NGO, city="Pune")
        blocked = User.objects.get(username="blocked_ngo")
        blocked.is_blocked = True
        blocked.save(update_fields=["is_blocked"])
        self.client.force_login(self.admin)

        response = self.client.get(reverse("accounts:admin_users"), {"role": "ngo"})
        self.assertContains(response, "pending_ngo")
        self.assertContains(response, "blocked_ngo")

        response = self.client.get(reverse("accounts:admin_users"), {"status": "blocked"})
        self.assertContains(response, "blocked_ngo")
        self.assertNotContains(response, "pending_ngo")

        response = self.client.get(
            reverse("accounts:admin_users"), {"status": "unverified"}
        )
        self.assertContains(response, "pending_ngo")

    def test_admin_user_detail_returns_200(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("accounts:admin_user_detail", args=[self.ngo.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.ngo.display_name)


class ProfileTests(TestCase):
    def setUp(self):
        self.user = make_user("profile_user")
        self.client.force_login(self.user)

    def test_profile_update_changes_user_fields(self):
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "Updated",
                "last_name": "Name",
                "email": "updated@example.com",
                "phone": "+91 90000 99999",
                "city": "Pune",
                "address": "99 New Address",
                "profile-organization_name": "",
                "profile-donor_type": "individual",
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Updated")
        self.assertEqual(self.user.email, "updated@example.com")
        self.assertEqual(self.user.city, "Pune")

    def test_profile_email_must_be_unique(self):
        other = make_user("other_user", email="other@example.com")
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "Profile",
                "last_name": "User",
                "email": other.email,
                "phone": "",
                "city": "Mumbai",
                "address": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Another account already uses this email")
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.email, other.email)

    def test_password_change(self):
        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": DEFAULT_PASSWORD,
                "new_password1": "BrandNewPass456!",
                "new_password2": "BrandNewPass456!",
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("BrandNewPass456!"))

    def test_volunteer_can_toggle_availability(self):
        volunteer = make_user("toggle_vol", role=User.Role.VOLUNTEER)
        self.client.force_login(volunteer)
        self.assertFalse(volunteer.volunteer_profile.is_available is False)
        response = self.client.post(reverse("accounts:toggle_availability"))
        self.assertRedirects(response, reverse("accounts:volunteer_dashboard"))
        volunteer.volunteer_profile.refresh_from_db()
        self.assertFalse(volunteer.volunteer_profile.is_available)

    def test_donor_cannot_toggle_volunteer_availability(self):
        response = self.client.post(reverse("accounts:toggle_availability"))
        self.assertEqual(response.status_code, 403)
