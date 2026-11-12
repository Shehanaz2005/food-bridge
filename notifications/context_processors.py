def notifications(request):
    if not request.user.is_authenticated:
        return {
            "unread_notifications_count": 0,
            "recent_notifications": [],
        }
    unread = request.user.notifications.filter(is_read=False)
    return {
        "unread_notifications_count": unread.count(),
        "recent_notifications": list(unread[:5]),
    }
