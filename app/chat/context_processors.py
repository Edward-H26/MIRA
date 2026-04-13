from app.services import neo4j_memory as neo4j


def _user_id(request):
    try:
        profile = request.user.profile
        return str(profile.pk)
    except Exception:
        return str(request.user.pk)


def user_sessions(request):
    if not request.user.is_authenticated:
        return {"sessions": []}
    try:
        sessions = neo4j.get_sessions_for_user(_user_id(request))
        return {"sessions": sessions}
    except Exception:
        return {"sessions": []}


def user_notifications(request):
    if not request.user.is_authenticated:
        return {"unreadNotificationCount": 0, "recentNotifications": []}
    try:
        uid = _user_id(request)
        return {
            "unreadNotificationCount": neo4j.get_unread_notification_count(uid),
            "recentNotifications": neo4j.get_notifications(uid, limit=5),
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
