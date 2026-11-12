"""Reusable upload validators for profile and food images."""

from pathlib import Path

from django.core.exceptions import ValidationError

MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def validate_image_file(upload):
    """Validate extension and file size for uploaded images.

    Pillow (through Django's ImageField) verifies that the file is a real,
    decodable image. This validator adds an explicit whitelist and size limit
    so unsafe or oversized uploads are rejected with a readable message.
    """
    if not upload:
        return

    extension = Path(getattr(upload, "name", "")).suffix.lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError("Upload a JPG, PNG, or WebP image.")

    size = getattr(upload, "size", 0)
    if size > MAX_IMAGE_SIZE:
        raise ValidationError("Image size must be 5 MB or smaller.")
