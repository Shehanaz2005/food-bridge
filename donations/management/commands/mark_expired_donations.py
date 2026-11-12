from django.core.management.base import BaseCommand

from donations.expiry import expire_overdue_donations, send_expiry_warnings


class Command(BaseCommand):
    help = (
        "Expire overdue food donations, close their requests, and warn users about "
        "food approaching expiry. Schedule this command every 15–30 minutes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--warn-hours",
            type=int,
            default=6,
            help="Warn about donations expiring within this many hours (default: 6).",
        )
        parser.add_argument(
            "--no-warnings",
            action="store_true",
            help="Only expire overdue donations; skip expiry warnings.",
        )

    def handle(self, *args, **options):
        expired = expire_overdue_donations()
        self.stdout.write(self.style.SUCCESS(f"Expired {expired} overdue donation(s)."))

        if not options["no_warnings"]:
            warned = send_expiry_warnings(hours=max(1, options["warn_hours"]))
            self.stdout.write(
                self.style.SUCCESS(f"Sent expiry warnings for {warned} donation(s).")
            )
