"""Role-based access-control decorators."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def role_required(*roles):
    """Allow only authenticated users whose role is in ``roles``."""

    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if request.user.is_blocked:
                return redirect("accounts:login")
            if request.user.role not in roles:
                raise PermissionDenied("Your account role cannot access this page.")
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def admin_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied("Administrator access is required.")
        return view_func(request, *args, **kwargs)

    return wrapper
