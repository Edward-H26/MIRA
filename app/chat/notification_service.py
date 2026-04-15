from app.services import neo4j_memory as neo4j
from app.services import pusher_service as pusher


def _get_profile(user):
    from app.chat.service import get_or_create_profile_for_user
    return get_or_create_profile_for_user(user)


def create_notification(
    user,
    title: str,
    message: str,
    notification_type: int,
    related_url: str = "",
) -> dict:
    profile = _get_profile(user)
    userId = str(profile.pk)

    result = neo4j.create_notification(
        user_id=userId,
        title=title,
        message=message,
        notification_type=notification_type,
        related_url=related_url,
    )

    pusher.send_notification(userId, {
        "id": result.get("id", ""),
        "title": title,
        "message": message,
        "notificationType": notification_type,
        "relatedUrl": related_url,
    })

    return {
        "id": result.get("id", ""),
        "title": result.get("title", ""),
        "message": result.get("message", ""),
        "isRead": result.get("isRead", False),
        "createdAt": result.get("createdAt", ""),
    }


def get_unread_count(user) -> int:
    profile = _get_profile(user)
    return neo4j.get_unread_notification_count(str(profile.pk))


def get_recent_notifications(user, limit: int = 10) -> list[dict]:
    profile = _get_profile(user)
    notifications = neo4j.get_notifications(
        user_id=str(profile.pk),
        unread_only=False,
        limit=limit,
    )
    return [
        {
            "id": n.get("id", ""),
            "title": n.get("title", ""),
            "message": n.get("message", ""),
            "notificationType": n.get("notificationType", 0),
            "isRead": n.get("isRead", False),
            "relatedUrl": n.get("relatedUrl", ""),
            "createdAt": n.get("createdAt", ""),
        }
        for n in notifications
    ]


def _invalidate_notification_cache(uid: str) -> None:
    """The user_notifications context processor caches counts with a 10s TTL.
    Without invalidation the unread badge keeps showing the stale count for
    up to 10 seconds after the user opens or dismisses notifications."""
    try:
        from django.core.cache import cache
        cache.delete(f"chat:ctx:notifications:{uid}")
    except Exception:
        pass


def mark_notification_read(user, notification_id: str) -> None:
    neo4j.mark_notification_read(notification_id)
    profile = _get_profile(user)
    _invalidate_notification_cache(str(profile.pk))


def mark_all_read(user) -> int:
    profile = _get_profile(user)
    uid = str(profile.pk)
    result = neo4j.mark_all_notifications_read(uid)
    _invalidate_notification_cache(uid)
    return result


def mark_read_by_related_url(user, related_url: str) -> int:
    if not related_url:
        return 0
    profile = _get_profile(user)
    uid = str(profile.pk)
    result = neo4j.mark_notifications_read_by_related_url(uid, related_url)
    _invalidate_notification_cache(uid)
    return result


def dismiss_notification(user, notification_id: str) -> None:
    mark_notification_read(user, notification_id)
