from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from food_bridge.test_utils import make_admin, make_donation, make_user
from notifications.models import Notification
from support.models import IssueReport
from tracking.models import AuditLog


class IssueReportingTests(TestCase):
    def setUp(self):
        self.user = make_user("issue_reporter")
        self.other = make_user("issue_other")
        self.admin = make_admin("issue_admin")
        self.own_donation = make_donation(self.user, food_name="My Issue Donation")
        self.other_donation = make_donation(self.other, food_name="Other Issue Donation")

    def test_login_required(self):
        response = self.client.get(reverse("support:report_issue"))
        self.assertEqual(response.status_code, 302)

    def test_user_can_report_issue_and_staff_are_notified(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("support:report_issue"),
            {
                "category": "donation",
                "subject": "Pickup address is hard to find",
                "description": "The gate is behind the main building.",
                "related_donation": self.own_donation.pk,
            },
        )
        self.assertRedirects(response, reverse("support:report_issue"))
        issue = IssueReport.objects.get(subject="Pickup address is hard to find")
        self.assertEqual(issue.reporter, self.user)
        self.assertEqual(issue.related_donation, self.own_donation)
        self.assertEqual(issue.status, IssueReport.Status.OPEN)
        self.assertTrue(
            Notification.objects.filter(
                user=self.admin, title="New issue reported"
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(action="issue_reported", actor=self.user).exists()
        )

    def test_user_cannot_link_someone_elses_donation(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("support:report_issue"),
            {
                "category": "donation",
                "subject": "Unrelated report",
                "description": "This should not be allowed.",
                "related_donation": self.other_donation.pk,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "only link an issue to your own donation activity")
        self.assertFalse(IssueReport.objects.filter(subject="Unrelated report").exists())

    def test_user_sees_recent_issues_on_report_page(self):
        IssueReport.objects.create(
            reporter=self.user,
            subject="Existing report",
            category=IssueReport.Category.TECHNICAL,
            description="A technical problem.",
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("support:report_issue"))
        self.assertContains(response, "Existing report")


class AdminIssueTests(TestCase):
    def setUp(self):
        self.admin = make_admin("support_admin")
        self.user = make_user("support_user")
        self.issue = IssueReport.objects.create(
            reporter=self.user,
            subject="Order never arrived",
            category=IssueReport.Category.DELIVERY,
            description="The volunteer did not arrive.",
        )

    def test_non_staff_cannot_open_issue_queue(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("support:admin_issues"))
        self.assertEqual(response.status_code, 403)

    def test_admin_can_filter_issues(self):
        IssueReport.objects.create(
            reporter=self.user,
            subject="Resolved technical issue",
            category=IssueReport.Category.TECHNICAL,
            description="Already fixed.",
            status=IssueReport.Status.RESOLVED,
        )
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("support:admin_issues"), {"status": IssueReport.Status.OPEN}
        )
        self.assertContains(response, "Order never arrived")
        self.assertNotContains(response, "Resolved technical issue")

        response = self.client.get(reverse("support:admin_issues"), {"q": "technical"})
        self.assertContains(response, "Resolved technical issue")
        self.assertNotContains(response, "Order never arrived")

    def test_admin_can_resolve_issue_and_notify_reporter(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("support:admin_issue_update", args=[self.issue.pk]),
            {"status": IssueReport.Status.RESOLVED, "admin_notes": "Spoke with the volunteer."},
        )
        self.assertRedirects(response, reverse("support:admin_issues"))
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.status, IssueReport.Status.RESOLVED)
        self.assertEqual(self.issue.admin_notes, "Spoke with the volunteer.")
        self.assertEqual(self.issue.resolved_by, self.admin)
        self.assertIsNotNone(self.issue.resolved_at)
        self.assertTrue(
            Notification.objects.filter(
                user=self.user, title__icontains="issue report was updated"
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(action="issue_updated", actor=self.admin).exists()
        )

    def test_reopening_issue_clears_resolution_metadata(self):
        self.issue.status = IssueReport.Status.RESOLVED
        self.issue.resolved_by = self.admin
        self.issue.resolved_at = timezone.now()
        self.issue.save()
        self.client.force_login(self.admin)
        self.client.post(
            reverse("support:admin_issue_update", args=[self.issue.pk]),
            {"status": IssueReport.Status.IN_REVIEW, "admin_notes": "Reopened."},
        )
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.status, IssueReport.Status.IN_REVIEW)
        self.assertIsNone(self.issue.resolved_by)
        self.assertIsNone(self.issue.resolved_at)

    def test_issue_status_css(self):
        self.assertEqual(self.issue.status_css, "warning")
        self.issue.status = IssueReport.Status.RESOLVED
        self.assertEqual(self.issue.status_css, "success")

    def test_issue_update_requires_post_and_staff(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("support:admin_issue_update", args=[self.issue.pk])
        )
        self.assertEqual(response.status_code, 403)
