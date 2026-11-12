from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect


class BlockedUserMiddleware:
    """Immediately end sessions for accounts blocked by an administrator."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and getattr(request.user, "is_blocked", False):
            logout(request)
            messages.error(
                request,
                "This account has been blocked. Contact the Food Bridge team if you need help.",
            )
            return redirect("accounts:login")
        return self.get_response(request)
