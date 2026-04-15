from django.core.cache import cache

from app.services import neo4j_memory as neo4j

# Context processors run on every authenticated page render, triggering 3-4
# Neo4j round trips per load. A short in-process cache (Django's default
# LocMemCache) cuts repeat lookups without introducing any new dependency; the
# TTLs are short enough that mutations (new messages, new notifications) show
# up within a few seconds on the next page load.

_SESSIONS_TTL = 20  # seconds
_NOTIFICATIONS_TTL = 10
_AGENTS_TTL = 60


def _user_id(request):
    try:
        profile = request.user.profile
        return str(profile.pk)
    except Exception:
        return str(request.user.pk)


def _cached(request, key: str, ttl: int, loader):
    """Cache ``loader()`` under a per-user key. First hits in a given process
    pay the Neo4j cost; subsequent hits within ``ttl`` seconds reuse the
    cached result. Falls back to ``loader()`` if the cache misses or fails."""
    try:
        hit = cache.get(key)
        if hit is not None:
            return hit
    except Exception:
        pass
    value = loader()
    try:
        cache.set(key, value, ttl)
    except Exception:
        pass
    return value


def user_sessions(request):
    if not request.user.is_authenticated:
        return {"sessions": []}
    uid = _user_id(request)
    try:
        sessions = _cached(
            request,
            f"chat:ctx:sessions:{uid}",
            _SESSIONS_TTL,
            lambda: _merged_sessions_for_user(uid),
        )
        return {"sessions": sessions}
    except Exception:
        return {"sessions": []}


def _merged_sessions_for_user(uid: str) -> list:
    """Union of sessions the user CREATED and sessions they only MEMBER_OF.
    Without this merge the sidebar hides any group the user joined but did
    not create, so the sidebar "Groups" section appears empty for invitees."""
    owned = neo4j.get_sessions_for_user(uid) or []
    memberOnly = []
    try:
        memberSessions = neo4j.get_sessions_for_member(uid) or []
        ownedIds = {str(s.get("id", "")) for s in owned}
        for s in memberSessions:
            sid = str(s.get("id", ""))
            if not sid or sid in ownedIds:
                continue
            memberOnly.append(s)
    except Exception:
        pass

    combined = list(owned) + memberOnly
    combined.sort(
        key=lambda s: (s.get("updatedAt") or s.get("createdAt") or ""),
        reverse=True,
    )
    return combined


def user_notifications(request):
    if not request.user.is_authenticated:
        return {"unreadNotificationCount": 0, "recentNotifications": []}
    try:
        uid = _user_id(request)
        data = _cached(
            request,
            f"chat:ctx:notifications:{uid}",
            _NOTIFICATIONS_TTL,
            lambda: {
                "unreadNotificationCount": neo4j.get_unread_notification_count(uid),
                "recentNotifications": neo4j.get_notifications(uid, limit=5),
            },
        )
        return data
    except Exception:
        return {"unreadNotificationCount": 0, "recentNotifications": []}


def user_agents(request):
    if not request.user.is_authenticated:
        return {"userAgents": []}
    try:
        from .agent_service import get_agents_for_user
        uid = _user_id(request)
        agents = _cached(
            request,
            f"chat:ctx:agents:{uid}",
            _AGENTS_TTL,
            lambda: get_agents_for_user(request.user),
        )
        return {"userAgents": agents}
    except Exception:
        return {"userAgents": []}


def pusher_config(request):
    from app.services.pusher_service import get_pusher_key, get_pusher_cluster
    return {
        "pusherKey": get_pusher_key(),
        "pusherCluster": get_pusher_cluster(),
    }
