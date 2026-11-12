"""Create a coherent demo dataset for local review.

Run once:
    python manage.py seed_demo

Recreate from scratch:
    python manage.py seed_demo --reset

The command is intentionally conservative: without --reset it refuses to
touch an existing database if any demo account already exists. Passwords are
set to the values printed at the end and documented in README.md.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import DonorProfile, NGOProfile, User, VolunteerProfile
from donations.models import DonationRequest, FoodDonation
from notifications.models import Notification
from notifications.services import notify
from tracking.models import DonationTracking
from tracking.services import log_audit
from volunteers.models import PickupAssignment

DEMO_PASSWORD = "FoodBridge123!"
DEMO_ADMIN_PASSWORD = "AdminPass123!"

DEMO_USERNAMES = [
    "admin",
    "spice_garden",
    "green_bowl",
    "sunrise_bakery",
    "anna_seva",
    "roti_bank",
    "hope_kitchen",
    "arjun_volunteer",
    "priya_volunteer",
    "samir_volunteer",
]

TRACKING_TITLES = {
    "available": "Donation created",
    "requested": "NGO requested food",
    "accepted": "Donor accepted request",
    "assigned": "Volunteer assigned",
    "picked_up": "Food picked up",
    "delivered": "Food delivered",
    "completed": "Donation completed",
    "expired": "Donation expired",
    "cancelled": "Donation cancelled",
}


class Command(BaseCommand):
    help = "Seed Food Bridge with demo users, donations, requests, assignments, and activity."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete demo accounts and their donations before recreating the dataset.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["reset"]:
            self._reset()
        elif User.objects.filter(username__in=DEMO_USERNAMES).exists():
            self.stdout.write(
                self.style.WARNING(
                    "Demo accounts already exist. Nothing changed. "
                    "Use --reset to recreate the demo dataset."
                )
            )
            return

        users = self._create_users()
        donations = self._create_donations(users)
        self._create_notifications(users, donations)
        self._create_audit(users, donations)

        self.stdout.write(self.style.SUCCESS("Food Bridge demo data is ready."))
        self.stdout.write("")
        self.stdout.write("Sign in at /accounts/login/ with:")
        self.stdout.write(f"  Administrator   admin / {DEMO_ADMIN_PASSWORD}")
        self.stdout.write(f"  Donor           spice_garden / {DEMO_PASSWORD}")
        self.stdout.write(f"  Verified NGO    anna_seva / {DEMO_PASSWORD}")
        self.stdout.write(f"  Volunteer       arjun_volunteer / {DEMO_PASSWORD}")
        self.stdout.write("")
        self.stdout.write(
            "Other demo accounts: green_bowl, sunrise_bakery, roti_bank, "
            "hope_kitchen, priya_volunteer, samir_volunteer."
        )

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------
    def _reset(self):
        demo_users = User.objects.filter(username__in=DEMO_USERNAMES)
        FoodDonation.objects.filter(donor__in=demo_users).delete()
        DonationRequest.objects.filter(ngo__in=demo_users).delete()
        PickupAssignment.objects.filter(volunteer__in=demo_users).delete()
        demo_users.delete()
        self.stdout.write(self.style.WARNING("Existing demo accounts removed."))

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------
    def _create_users(self):
        users = {}

        admin = User.objects.create_superuser(
            username="admin",
            email="admin@foodbridge.org",
            password=DEMO_ADMIN_PASSWORD,
            first_name="Ayesha",
            last_name="Rao",
            role=User.Role.ADMIN,
            city="Mumbai",
            phone="+91 98200 10001",
        )
        users["admin"] = admin

        donor_specs = [
            {
                "username": "spice_garden",
                "email": "hello@spicegarden.example",
                "first_name": "Rohan",
                "last_name": "Kapoor",
                "city": "Mumbai",
                "address": "14 Linking Road, Bandra West, Mumbai",
                "phone": "+91 98200 10002",
                "donor_type": DonorProfile.DonorType.RESTAURANT,
                "organization_name": "Spice Garden Restaurant",
            },
            {
                "username": "green_bowl",
                "email": "team@greenbowl.example",
                "first_name": "Meera",
                "last_name": "Iyer",
                "city": "Mumbai",
                "address": "22 Hill Road, Bandra West, Mumbai",
                "phone": "+91 98200 10003",
                "donor_type": DonorProfile.DonorType.HOTEL,
                "organization_name": "Green Bowl Cafe",
            },
            {
                "username": "sunrise_bakery",
                "email": "orders@sunrisebakery.example",
                "first_name": "Karan",
                "last_name": "Shah",
                "city": "Pune",
                "address": "5 FC Road, Shivajinagar, Pune",
                "phone": "+91 98200 10004",
                "donor_type": DonorProfile.DonorType.OTHER,
                "organization_name": "Sunrise Bakery",
            },
        ]
        for spec in donor_specs:
            user = User.objects.create_user(
                username=spec["username"],
                email=spec["email"],
                password=DEMO_PASSWORD,
                first_name=spec["first_name"],
                last_name=spec["last_name"],
                role=User.Role.DONOR,
                city=spec["city"],
                address=spec["address"],
                phone=spec["phone"],
            )
            DonorProfile.objects.update_or_create(
                user=user,
                defaults={
                    "donor_type": spec["donor_type"],
                    "organization_name": spec["organization_name"],
                },
            )
            users[spec["username"]] = user

        ngo_specs = [
            {
                "username": "anna_seva",
                "email": "contact@annaseva.example",
                "city": "Mumbai",
                "address": "8 Sion East, Mumbai",
                "phone": "+91 98200 20001",
                "organization_name": "Anna Seva Foundation",
                "registration_number": "MH-NGO-2014-8891",
                "description": "Community kitchens serving freshly cooked meals to families in central Mumbai.",
                "contact_person": "Farah Sheikh",
                "website": "https://annaseva.example",
                "service_area": "Mumbai, Bandra, Sion, Dadar",
                "preferred_categories": ["cooked_meal", "bakery", "fruits_vegetables"],
                "minimum_quantity": 10,
                "minimum_unit": "meals",
                "verified": True,
            },
            {
                "username": "roti_bank",
                "email": "team@rotibank.example",
                "city": "Mumbai",
                "address": "31 Andheri West, Mumbai",
                "phone": "+91 98200 20002",
                "organization_name": "Roti Bank Trust",
                "registration_number": "MH-NGO-2018-2210",
                "description": "Collects surplus bread and cooked food for nightly street outreach.",
                "contact_person": "Vikram Desai",
                "website": "https://rotibank.example",
                "service_area": "Mumbai, Andheri, Juhu, Bandra",
                "preferred_categories": ["bakery", "cooked_meal", "packaged"],
                "minimum_quantity": 5,
                "minimum_unit": "kg",
                "verified": True,
            },
            {
                "username": "hope_kitchen",
                "email": "hello@hopekitchen.example",
                "city": "Pune",
                "address": "12 Koregaon Park, Pune",
                "phone": "+91 98200 20003",
                "organization_name": "Hope Kitchen",
                "registration_number": "MH-NGO-2025-7742",
                "description": "A new community kitchen awaiting verification.",
                "contact_person": "Neha Joshi",
                "website": "",
                "service_area": "Pune",
                "preferred_categories": ["cooked_meal", "dairy"],
                "minimum_quantity": 8,
                "minimum_unit": "meals",
                "verified": False,
            },
        ]
        for spec in ngo_specs:
            verified = spec.pop("verified")
            user = User.objects.create_user(
                username=spec["username"],
                email=spec["email"],
                password=DEMO_PASSWORD,
                first_name=spec["contact_person"].split()[0],
                last_name=spec["contact_person"].split()[-1],
                role=User.Role.NGO,
                city=spec["city"],
                address=spec["address"],
                phone=spec["phone"],
            )
            NGOProfile.objects.update_or_create(
                user=user,
                defaults={
                    "organization_name": spec["organization_name"],
                    "registration_number": spec["registration_number"],
                    "description": spec["description"],
                    "contact_person": spec["contact_person"],
                    "website": spec["website"],
                    "service_area": spec["service_area"],
                    "preferred_categories": spec["preferred_categories"],
                    "minimum_quantity": spec["minimum_quantity"],
                    "minimum_unit": spec["minimum_unit"],
                    "verified": verified,
                    "verified_at": timezone.now() if verified else None,
                    "verified_by": admin if verified else None,
                },
            )
            users[spec["username"]] = user

        volunteer_specs = [
            {
                "username": "arjun_volunteer",
                "email": "arjun@foodbridge.example",
                "first_name": "Arjun",
                "last_name": "Mehta",
                "city": "Mumbai",
                "address": "Bandra West, Mumbai",
                "phone": "+91 98200 30001",
                "vehicle_type": VolunteerProfile.Vehicle.BIKE,
                "service_area": "Bandra, Khar, Santacruz",
                "is_available": True,
                "bio": "Weekend rider happy to move meals across central Mumbai.",
            },
            {
                "username": "priya_volunteer",
                "email": "priya@foodbridge.example",
                "first_name": "Priya",
                "last_name": "Nair",
                "city": "Mumbai",
                "address": "Powai, Mumbai",
                "phone": "+91 98200 30002",
                "vehicle_type": VolunteerProfile.Vehicle.CAR,
                "service_area": "Powai, Andheri, Sion",
                "is_available": True,
                "bio": "Can handle larger deliveries after 6 pm on weekdays.",
            },
            {
                "username": "samir_volunteer",
                "email": "samir@foodbridge.example",
                "first_name": "Samir",
                "last_name": "Khan",
                "city": "Pune",
                "address": "Kothrud, Pune",
                "phone": "+91 98200 30003",
                "vehicle_type": VolunteerProfile.Vehicle.VAN,
                "service_area": "Pune",
                "is_available": False,
                "bio": "Available for bulk pickups on weekends.",
            },
        ]
        for spec in volunteer_specs:
            user = User.objects.create_user(
                username=spec["username"],
                email=spec["email"],
                password=DEMO_PASSWORD,
                first_name=spec["first_name"],
                last_name=spec["last_name"],
                role=User.Role.VOLUNTEER,
                city=spec["city"],
                address=spec["address"],
                phone=spec["phone"],
            )
            VolunteerProfile.objects.update_or_create(
                user=user,
                defaults={
                    "vehicle_type": spec["vehicle_type"],
                    "service_area": spec["service_area"],
                    "is_available": spec["is_available"],
                    "bio": spec["bio"],
                },
            )
            users[spec["username"]] = user

        return users

    # ------------------------------------------------------------------
    # Donations
    # ------------------------------------------------------------------
    def _create_donations(self, users):
        now = timezone.now()
        donations = {}

        def donation(
            key,
            donor,
            food_name,
            category,
            quantity,
            unit,
            prepared_delta,
            expires_delta,
            status,
            *,
            city=None,
            address=None,
            contact=None,
            phone=None,
            description="",
            handling="",
            vegetarian=True,
            created_delta=None,
            completed_delta=None,
            cancelled_reason="",
        ):
            donor_user = users[donor]
            pickup_city = city or donor_user.city
            obj = FoodDonation.objects.create(
                donor=donor_user,
                food_name=food_name,
                category=category,
                description=description,
                quantity=quantity,
                unit=unit,
                prepared_at=now + timedelta(hours=prepared_delta),
                expires_at=now + timedelta(hours=expires_delta),
                pickup_address=address or donor_user.address,
                pickup_city=pickup_city,
                pickup_contact_name=contact or donor_user.display_name,
                pickup_contact_phone=phone or donor_user.phone,
                handling_instructions=handling,
                is_vegetarian=vegetarian,
                status=status,
                cancelled_reason=cancelled_reason,
                created_at=now + timedelta(hours=created_delta or 0),
                completed_at=now + timedelta(hours=completed_delta) if completed_delta else None,
            )
            donations[key] = obj
            return obj

        # 1. Live listing.
        d1 = donation(
            "available",
            "spice_garden",
            "Vegetable Biryani",
            "cooked_meal",
            40,
            "meals",
            -1,
            8,
            FoodDonation.Status.AVAILABLE,
            description="Freshly prepared vegetable biryani packed in food-grade trays after the lunch service.",
            handling="Keep covered and refrigerate if not collected within two hours. Reheat thoroughly before serving.",
            created_delta=-1,
        )
        self._events(d1, ["available"], now, -1)

        # 2. Pending request from a verified NGO.
        d2 = donation(
            "requested",
            "green_bowl",
            "Assorted Sandwiches",
            "cooked_meal",
            25,
            "meals",
            -1,
            12,
            FoodDonation.Status.REQUESTED,
            description="Vegetarian sandwiches prepared for an office event; individually wrapped and unserved.",
            handling="Keep refrigerated. Best consumed within the next 12 hours.",
            created_delta=-2,
        )
        self._request(
            d2,
            users["anna_seva"],
            DonationRequest.Status.PENDING,
            25,
            "We can collect within the hour and serve them at our evening community meal.",
            now,
            -1,
        )
        self._events(d2, ["available", "requested"], now, -2)

        # 3. Accepted, waiting for a volunteer.
        d3 = donation(
            "accepted",
            "spice_garden",
            "Fresh Fruit Boxes",
            "fruits_vegetables",
            18,
            "kg",
            -2,
            20,
            FoodDonation.Status.ACCEPTED,
            description="Whole seasonal fruit boxes from the restaurant's suppliers, inspected and packed this morning.",
            handling="Store in a cool, dry place. Wash before serving.",
            created_delta=-3,
        )
        self._request(
            d3,
            users["roti_bank"],
            DonationRequest.Status.ACCEPTED,
            18,
            "We will distribute these boxes through our Saturday food drive.",
            now,
            -2,
            donor_note="Please collect from the service entrance.",
        )
        self._events(d3, ["available", "requested", "accepted"], now, -3)

        # 4. Assigned to a volunteer, awaiting acceptance.
        d4 = donation(
            "assigned",
            "green_bowl",
            "Bakery Surplus",
            "bakery",
            30,
            "packets",
            -1,
            10,
            FoodDonation.Status.ASSIGNED,
            description="Croissants, muffins, and bread rolls from today's bake, packed in paper bags.",
            handling="Keep in a dry box. Suitable for same-day distribution.",
            created_delta=-2,
        )
        self._request(
            d4,
            users["anna_seva"],
            DonationRequest.Status.ACCEPTED,
            30,
            "Great for our morning breakfast service.",
            now,
            -1,
            donor_note="Call when you reach the back gate.",
        )
        self._assignment(
            d4,
            users["arjun_volunteer"],
            PickupAssignment.Status.OFFERED,
            users["admin"],
            "Collect from the cafe's service entrance and deliver to Anna Seva's kitchen.",
            now,
            -1,
        )
        self._events(d4, ["available", "requested", "accepted", "assigned"], now, -2)

        # 5. Picked up and in transit.
        d5 = donation(
            "picked_up",
            "spice_garden",
            "Dal & Rice",
            "cooked_meal",
            50,
            "meals",
            -3,
            6,
            FoodDonation.Status.PICKED_UP,
            description="Protein-rich dal and steamed rice prepared for the restaurant's lunch rush.",
            handling="Transport in insulated containers. Serve within four hours.",
            created_delta=-4,
        )
        self._request(
            d5,
            users["roti_bank"],
            DonationRequest.Status.ACCEPTED,
            50,
            "These meals are going straight to our night shelter.",
            now,
            -3,
            donor_note="Pickup after 3 pm.",
        )
        self._assignment(
            d5,
            users["priya_volunteer"],
            PickupAssignment.Status.PICKED_UP,
            users["admin"],
            "Insulated containers are at the pickup counter.",
            now,
            -1,
        )
        self._events(d5, ["available", "requested", "accepted", "assigned", "picked_up"], now, -4)

        # 6. Delivered, waiting for NGO receipt confirmation.
        d6 = donation(
            "delivered",
            "sunrise_bakery",
            "Paneer Curry",
            "cooked_meal",
            20,
            "kg",
            -4,
            12,
            FoodDonation.Status.DELIVERED,
            description="Fresh paneer curry prepared for a cancelled banquet order.",
            handling="Keep refrigerated until serving. Reheat to a safe temperature.",
            created_delta=-5,
            city="Pune",
        )
        self._request(
            d6,
            users["hope_kitchen"],
            DonationRequest.Status.ACCEPTED,
            20,
            "We can serve this at our community kitchen tonight.",
            now,
            -4,
            donor_note="Packed in sealed catering trays.",
        )
        self._assignment(
            d6,
            users["samir_volunteer"],
            PickupAssignment.Status.DELIVERED,
            users["admin"],
            "Delivered directly to Hope Kitchen's kitchen door.",
            now,
            -2,
        )
        self._events(
            d6,
            ["available", "requested", "accepted", "assigned", "picked_up", "delivered"],
            now,
            -5,
        )

        # 7-10. Completed history spread over recent months for analytics.
        completed_specs = [
            (
                "completed_recent",
                "spice_garden",
                "Vegetable Pulao",
                "cooked_meal",
                60,
                "meals",
                "anna_seva",
                -72,
                -70,
                "Packed and handed to Anna Seva for their Sunday community lunch.",
            ),
            (
                "completed_bread",
                "green_bowl",
                "Bread & Pastries",
                "bakery",
                15,
                "kg",
                "roti_bank",
                -24 * 12,
                -24 * 12 + 2,
                "Assorted breads and pastries from the morning bake.",
            ),
            (
                "completed_fruit",
                "sunrise_bakery",
                "Seasonal Fruit Crates",
                "fruits_vegetables",
                24,
                "kg",
                "roti_bank",
                -24 * 38,
                -24 * 38 + 3,
                "Fruit crates collected from the bakery's supplier.",
            ),
            (
                "completed_meals",
                "spice_garden",
                "Chicken Biryani",
                "cooked_meal",
                80,
                "meals",
                "anna_seva",
                -24 * 70,
                -24 * 70 + 2,
                "Surplus biryani from a private event, delivered within the safe window.",
                False,
            ),
        ]
        for (
            key,
            donor,
            food_name,
            category,
            quantity,
            unit,
            ngo,
            created_delta,
            completed_delta,
            description,
            *rest,
        ) in completed_specs:
            vegetarian = rest[0] if rest else True
            obj = donation(
                key,
                donor,
                food_name,
                category,
                quantity,
                unit,
                created_delta - 4,
                completed_delta + 2,
                FoodDonation.Status.COMPLETED,
                description=description,
                handling="Handled according to Food Bridge food-safety guidance.",
                vegetarian=vegetarian,
                created_delta=created_delta,
                completed_delta=completed_delta,
            )
            self._request(
                obj,
                users[ngo],
                DonationRequest.Status.FULFILLED,
                quantity,
                "Received and distributed by our team.",
                now,
                created_delta,
                responded_delta=completed_delta - 1,
                donor_note="Thank you for sharing.",
            )
            self._assignment(
                obj,
                users["arjun_volunteer"] if ngo == "anna_seva" else users["priya_volunteer"],
                PickupAssignment.Status.COMPLETED,
                users["admin"],
                "Completed delivery.",
                now,
                created_delta + 1,
                completed_delta=completed_delta,
            )
            self._events(
                obj,
                ["available", "requested", "accepted", "assigned", "picked_up", "delivered", "completed"],
                now,
                created_delta,
                completed_at=completed_delta,
            )

        # 11. Expired listing.
        d_expired = donation(
            "expired",
            "green_bowl",
            "Yogurt Cups",
            "dairy",
            12,
            "pieces",
            -10,
            -2,
            FoodDonation.Status.EXPIRED,
            description="Chilled yogurt cups left from a breakfast buffet.",
            handling="Keep refrigerated.",
            created_delta=-10,
        )
        self._request(
            d_expired,
            users["roti_bank"],
            DonationRequest.Status.EXPIRED,
            12,
            "Can collect in the evening.",
            now,
            -9,
            donor_note="The food expired before it could be collected.",
        )
        self._events(d_expired, ["available", "requested", "expired"], now, -10)

        # 12. Cancelled listing.
        d_cancelled = donation(
            "cancelled",
            "spice_garden",
            "Event Leftovers",
            "cooked_meal",
            35,
            "meals",
            -6,
            6,
            FoodDonation.Status.CANCELLED,
            description="Trays prepared for a corporate event that was cancelled.",
            handling="Refrigerate immediately.",
            created_delta=-6,
            cancelled_reason="The event was cancelled and the kitchen retained the food for staff meals.",
        )
        self._request(
            d_cancelled,
            users["anna_seva"],
            DonationRequest.Status.CANCELLED,
            35,
            "We can collect after 7 pm.",
            now,
            -5,
            donor_note="The donor cancelled this donation.",
        )
        self._events(d_cancelled, ["available", "requested", "cancelled"], now, -6)

        return donations

    # ------------------------------------------------------------------
    # Related rows
    # ------------------------------------------------------------------
    def _request(
        self,
        donation,
        ngo,
        status,
        quantity,
        message,
        now,
        created_delta,
        donor_note="",
        responded_delta=None,
    ):
        return DonationRequest.objects.create(
            donation=donation,
            ngo=ngo,
            quantity=quantity,
            message=message,
            status=status,
            donor_note=donor_note,
            created_at=now + timedelta(hours=created_delta),
            responded_at=(
                now + timedelta(hours=responded_delta)
                if responded_delta is not None
                else None
            ),
        )

    def _assignment(
        self,
        donation,
        volunteer,
        status,
        assigned_by,
        notes,
        now,
        created_delta,
        completed_delta=None,
    ):
        accepted_at = now + timedelta(hours=created_delta + 0.5) if status != PickupAssignment.Status.OFFERED else None
        picked_up_at = (
            now + timedelta(hours=created_delta + 1)
            if status
            in {
                PickupAssignment.Status.PICKED_UP,
                PickupAssignment.Status.DELIVERED,
                PickupAssignment.Status.COMPLETED,
            }
            else None
        )
        delivered_at = (
            now + timedelta(hours=created_delta + 2)
            if status
            in {PickupAssignment.Status.DELIVERED, PickupAssignment.Status.COMPLETED}
            else None
        )
        return PickupAssignment.objects.create(
            donation=donation,
            volunteer=volunteer,
            assigned_by=assigned_by,
            status=status,
            notes=notes,
            created_at=now + timedelta(hours=created_delta),
            accepted_at=accepted_at,
            picked_up_at=picked_up_at,
            delivered_at=delivered_at,
            completed_at=(
                now + timedelta(hours=completed_delta)
                if completed_delta is not None
                else None
            ),
        )

    def _events(self, donation, statuses, now, start_delta, completed_at=None):
        step = 0
        for status in statuses:
            if status != "completed" and completed_at is not None:
                created_at = now + timedelta(hours=start_delta + step * 0.25)
            elif status == "completed" and completed_at is not None:
                created_at = now + timedelta(hours=completed_at)
            else:
                created_at = now + timedelta(hours=start_delta + step * 0.25)
            event = DonationTracking.objects.create(
                donation=donation,
                status=status,
                title=TRACKING_TITLES.get(status, status.title()),
                description=self._event_description(donation, status),
                actor=donation.donor if status in {"available"} else None,
                created_at=created_at,
            )
            event.save(update_fields=["created_at"])
            step += 1

    def _event_description(self, donation, status):
        return {
            "available": f"{donation.quantity_display} of {donation.food_name} is available for rescue.",
            "requested": "A verified NGO submitted a request.",
            "accepted": "The donor allocated this donation to the requesting NGO.",
            "assigned": "A volunteer was assigned to collect the food.",
            "picked_up": "The volunteer collected the food from the donor.",
            "delivered": "The food was delivered to the recipient NGO.",
            "completed": "The recipient NGO confirmed receipt and the donation is complete.",
            "expired": "The safe consumption window passed before pickup.",
            "cancelled": "The donor cancelled this donation.",
        }.get(status, "")

    # ------------------------------------------------------------------
    # Notifications and audit trail
    # ------------------------------------------------------------------
    def _create_notifications(self, users, donations):
        notify(
            users["anna_seva"],
            "Your food request was accepted",
            "Spice Garden Restaurant accepted your request for Fresh Fruit Boxes. A volunteer will be assigned for pickup.",
            level=Notification.Level.SUCCESS,
            url=f"/donations/{donations['accepted'].pk}/",
        )
        notify(
            users["arjun_volunteer"],
            "New pickup assignment",
            "You have been assigned to collect Bakery Surplus from Green Bowl Cafe. Please accept or decline the assignment.",
            level=Notification.Level.INFO,
            url="/volunteer/assignments/",
        )
        notify(
            users["hope_kitchen"],
            "Food delivered — please confirm receipt",
            "Paneer Curry was delivered. Confirm receipt to complete the donation.",
            level=Notification.Level.SUCCESS,
            url=f"/donations/{donations['delivered'].pk}/",
        )
        notify(
            users["spice_garden"],
            "Food picked up",
            "Priya Nair collected Dal & Rice for delivery to Roti Bank Trust.",
            level=Notification.Level.SUCCESS,
            url=f"/donations/{donations['picked_up'].pk}/",
        )
        notify(
            users["admin"],
            "New issue reported",
            "Samir Khan reported: Pickup address needs a landmark.",
            level=Notification.Level.WARNING,
            url="/dashboard/admin/issues/",
        )
        notify(
            users["roti_bank"],
            "Food is approaching expiry",
            "Dal & Rice expires within 6 hours. Please coordinate the pickup quickly to avoid waste.",
            level=Notification.Level.WARNING,
            url=f"/donations/{donations['picked_up'].pk}/",
        )

    def _create_audit(self, users, donations):
        entries = [
            (users["admin"], "ngo_verified", "Verified organisation Anna Seva Foundation."),
            (users["admin"], "ngo_verified", "Verified organisation Roti Bank Trust."),
            (users["spice_garden"], "donation_created", "Created donation “Vegetable Biryani”."),
            (users["anna_seva"], "donation_requested", "Requested 25 meals of “Assorted Sandwiches”."),
            (users["admin"], "volunteer_assigned", "Assigned Arjun Mehta to “Bakery Surplus”."),
            (users["priya_volunteer"], "food_picked_up", "Picked up “Dal & Rice”."),
            (users["hope_kitchen"], "donation_requested", "Requested 20 kg of “Paneer Curry”."),
            (users["green_bowl"], "donation_cancelled", "Cancelled “Yogurt Cups” after expiry."),
        ]
        for actor, action, description in entries:
            log_audit(actor=actor, action=action, obj=None, description=description)
