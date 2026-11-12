"""Test-only settings tuned for a fast local suite.

Run the suite with:
    python manage.py test --settings=food_bridge.test_settings

Only the password hasher differs from production settings; everything else
(security middleware, database, apps) matches the real configuration.
"""

from .settings import *  # noqa: F401,F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
