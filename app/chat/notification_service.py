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


def mark_notification_read(user, notification_id: str) -> None:
    neo4j.mark_notification_read(notification_id)


def mark_all_read(user) -> int:
    profile = _get_profile(user)
    return neo4j.mark_all_notifications_read(str(profile.pk))


def mark_read_by_related_url(user, related_url: str) -> int:
    if not related_url:
        return 0
    profile = _get_profile(user)
    return neo4j.mark_notifications_read_by_related_url(str(profile.pk), related_url)


def dismiss_notification(user, notification_id: str) -> None:
    mark_notification_read(user, notification_id)
