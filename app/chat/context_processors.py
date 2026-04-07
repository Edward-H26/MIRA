from .service import get_sidebar_sessions_for_user


def user_sessions(request):
    if not request.user.is_authenticated:
        return {"sessions": []}
    return {"sessions": get_sidebar_sessions_for_user(request.user)}


def user_notifications(request):
    if not request.user.is_authenticated:
        return {"unreadNotificationCount": 0, "recentNotifications": []}
    try:
        from .notification_service import get_unread_count, get_recent_notifications
        return {
            "unreadNotificationCount": get_unread_count(request.user),
            "recentNotifications": get_recent_notifications(request.user, limit=5),
        }
    except Exception:
        return {"unreadNotificationCount": 0, "recentNotifications": []}


def user_agents(request):
    if not request.user.is_authenticated:
        return {"userAgents": []}
    try:
        from .agent_service import get_agents_for_user
        return {"userAgents": get_agents_for_user(request.user)}
    except Exception:
        return {"userAgents": []}


def pusher_config(request):
    from app.services.pusher_service import get_pusher_key, get_pusher_cluster
    return {
        "pusherKey": get_pusher_key(),
        "pusherCluster": get_pusher_cluster(),
    }
