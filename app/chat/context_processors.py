import logging

from django.core.cache import cache

from app.services import neo4j_memory as neo4j

logger = logging.getLogger(__name__)

# Context processors run on every authenticated page render, triggering 3-4
# Neo4j round trips per load. A short in-process cache (Django's default
# LocMemCache) cuts repeat lookups without introducing any new dependency; the
# TTLs are short enough that mutations (new messages, new notifications) show
# up within a few seconds on the next page load.

_SESSIONS_TTL = 20  # seconds
_NOTIFICATIONS_TTL = 10
_AGENTS_TTL = 60


def _user_id(request) -> str:
    """Resolve the canonical Neo4j :User.id for the requester. Returns "" on
    failure; callers MUST treat the empty string as "unauthenticated" and
    return their empty default. Never fall back to request.user.pk — that id
    lives in a different integer sequence than UserProfile.pk and causes
    cross-user data leaks when the two spaces collide numerically."""
    try:
        from app.users.services import get_or_create_profile_for_user
        profile = get_or_create_profile_for_user(request.user)
        return str(profile.pk)
    except Exception:
        logger.error(
            "ctx_processor_profile_resolution_failed",
            extra={"user_pk": getattr(request.user, "pk", None)},
            exc_info=True,
        )
        return ""


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
    if not uid:
        return {"sessions": []}
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
    """Sessions the user CREATED or joined as a MEMBER_OF, merged and sorted in
    a single Cypher round trip so the sidebar does not pay two queries plus a
    Python merge on every authenticated page load."""
    try:
        return neo4j.get_all_sessions_for_user(uid) or []
    except Exception:
        return []


def user_notifications(request):
    if not request.user.is_authenticated:
        return {"unreadNotificationCount": 0, "recentNotifications": []}
    uid = _user_id(request)
    if not uid:
        return {"unreadNotificationCount": 0, "recentNotifications": []}
    try:
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
    uid = _user_id(request)
    if not uid:
        return {"userAgents": []}
    try:
        from .agent_service import get_agents_for_user
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
