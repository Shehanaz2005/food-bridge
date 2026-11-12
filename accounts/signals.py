from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import DonorProfile, NGOProfile, User, VolunteerProfile


@receiver(post_save, sender=User)
def ensure_role_profile(sender, instance, created, **kwargs):
    """Every non-admin account gets exactly one profile for its role."""
    if instance.role == User.Role.DONOR:
        DonorProfile.objects.get_or_create(
            user=instance,
            defaults={"organization_name": ""},
        )
    elif instance.role == User.Role.NGO:
        NGOProfile.objects.get_or_create(
            user=instance,
            defaults={
                "organization_name": instance.get_full_name() or instance.username,
            },
        )
    elif instance.role == User.Role.VOLUNTEER:
        VolunteerProfile.objects.get_or_create(
            user=instance,
            defaults={"service_area": instance.city},
        )
