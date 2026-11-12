from django.test import RequestFactory, TestCase
from django.urls import reverse

from food_bridge.test_utils import make_user
from notifications.context_processors import notifications as notification_context
from notifications.models import Notification
from notifications.services import notify, notify_many


class NotificationServiceTests(TestCase):
    def setUp(self):
        self.user = make_user("note_user")

    def test_notify_creates_notification(self):
        note = notify(
            self.user,
            "Welcome",
            "Welcome to Food Bridge.",
            level=Notification.Level.SUCCESS,
            url="/notifications/",
        )
        self.assertEqual(note.user, self.user)
        self.assertEqual(note.level, Notification.Level.SUCCESS)
        self.assertFalse(note.is_read)

    def test_event_key_prevents_duplicates(self):
        first = notify(self.user, "Expiry", "Food expires soon.", event_key="expiry:1")
        second = notify(self.user, "Expiry", "Food expires soon.", event_key="expiry:1")
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(Notification.objects.count(), 1)

    def test_notify_many_deduplicates_users(self):
        other = make_user("note_other")
        created = notify_many(
            [self.user, other, self.user],
            "Update",
            "A workflow update.",
        )
        self.assertEqual(len(created), 2)
        self.assertEqual(Notification.objects.count(), 2)

    def test_notify_ignores_missing_user(self):
        self.assertIsNone(notify(None, "Title", "Message"))


class NotificationViewTests(TestCase):
    def setUp(self):
        self.user = make_user("inbox_user")
        self.other = make_user("inbox_other")
        self.note = notify(
            self.user,
            "Your request was accepted",
            "Good news.",
            url="/donations/1/",
        )
        self.unread = notify(self.user, "Second note", "More news.")
        self.other_note = notify(self.other, "Private note", "For another user.")

    def test_list_only_shows_own_notifications(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("notifications:list"))
        self.assertContains(response, "Your request was accepted")
        self.assertNotContains(response, "Private note")

    def test_unread_filter(self):
        self.note.is_read = True
        self.note.save(update_fields=["is_read"])
        self.client.force_login(self.user)
        response = self.client.get(reverse("notifications:list"), {"unread": "1"})
        self.assertContains(response, "Second note")
        self.assertNotContains(response, "Your request was accepted")

    def test_mark_read_redirects_to_safe_url(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("notifications:mark_read", args=[self.note.pk])
        )
        self.assertRedirects(response, "/donations/1/", fetch_redirect_response=False)
        self.note.refresh_from_db()
        self.assertTrue(self.note.is_read)

    def test_mark_read_rejects_external_redirect(self):
        external = notify(self.user, "External", "Link outside", url="https://evil.example/")
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("notifications:mark_read", args=[external.pk])
        )
        self.assertRedirects(response, reverse("notifications:list"))

    def test_user_cannot_mark_another_users_notification(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("notifications:mark_read", args=[self.other_note.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.other_note.refresh_from_db()
        self.assertFalse(self.other_note.is_read)

    def test_mark_all_read(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("notifications:mark_all_read"))
        self.assertRedirects(response, reverse("notifications:list"))
        self.assertFalse(
            Notification.objects.filter(user=self.user, is_read=False).exists()
        )
        self.other_note.refresh_from_db()
        self.assertFalse(self.other_note.is_read)

    def test_mark_read_requires_post(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("notifications:mark_read", args=[self.note.pk])
        )
        self.assertEqual(response.status_code, 405)

    def test_context_processor_counts_unread_for_current_user(self):
        request = RequestFactory().get("/")
        request.user = self.user
        context = notification_context(request)
        self.assertEqual(context["unread_notifications_count"], 2)
        self.assertEqual(len(context["recent_notifications"]), 2)

    def test_context_processor_is_empty_for_anonymous_user(self):
        request = RequestFactory().get("/")
        from django.contrib.auth.models import AnonymousUser

        request.user = AnonymousUser()
        context = notification_context(request)
        self.assertEqual(context["unread_notifications_count"], 0)
        self.assertEqual(context["recent_notifications"], [])
