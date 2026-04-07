from app.chat.models.notification import Notification
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
    notif = Notification.objects.create(
        user=profile,
        title=title,
        message=message,
        notification_type=notification_type,
        related_url=related_url,
    )

    try:
        neo4j.create_notification(
            user_id=str(profile.pk),
            title=title,
            message=message,
            notification_type=notification_type,
            related_url=related_url,
        )
    except Exception:
        pass

    pusher.send_notification(str(profile.pk), {
        "id": str(notif.pk),
        "title": title,
        "message": message,
        "notificationType": notification_type,
        "relatedUrl": related_url,
    })

    return {
        "id": str(notif.pk),
        "title": notif.title,
        "message": notif.message,
        "isRead": notif.is_read,
        "createdAt": notif.created_at.isoformat() if notif.created_at else "",
    }


def get_unread_count(user) -> int:
    profile = _get_profile(user)
    return Notification.objects.filter(user=profile, is_read=False).count()


def get_recent_notifications(user, limit: int = 10) -> list[dict]:
    profile = _get_profile(user)
    qs = Notification.objects.filter(user=profile).order_by("-created_at")[:limit]
    return [
        {
            "id": str(n.pk),
            "title": n.title,
            "message": n.message,
            "notificationType": n.notification_type,
            "isRead": n.is_read,
            "relatedUrl": n.related_url,
            "createdAt": n.created_at.isoformat() if n.created_at else "",
        }
        for n in qs
    ]


def mark_notification_read(user, notification_id: str) -> None:
    profile = _get_profile(user)
    Notification.objects.filter(pk=notification_id, user=profile).update(is_read=True)
    try:
        neo4j.mark_notification_read(notification_id)
    except Exception:
        pass


def mark_all_read(user) -> int:
    profile = _get_profile(user)
    count = Notification.objects.filter(user=profile, is_read=False).update(is_read=True)
    try:
        neo4j.mark_all_notifications_read(str(profile.pk))
    except Exception:
        pass
    return count


def dismiss_notification(user, notification_id: str) -> None:
    mark_notification_read(user, notification_id)
