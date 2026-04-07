from app.chat.models.audit_log import AuditLog
from app.services import neo4j_memory as neo4j


def _get_profile(user):
    from app.chat.service import get_or_create_profile_for_user
    return get_or_create_profile_for_user(user)


def log_audit(
    user,
    event_type: str,
    description: str = "",
    agent_id: str | None = None,
    metadata: dict | None = None,
) -> dict:
    profile = _get_profile(user)

    kwargs = {
        "user": profile,
        "event_type": event_type,
        "description": description,
        "metadata": metadata or {},
    }
    if agent_id:
        try:
            from app.chat.models.agent import Agent
            kwargs["agent"] = Agent.objects.filter(pk=int(agent_id)).first()
        except (ValueError, TypeError):
            pass

    log = AuditLog.objects.create(**kwargs)

    try:
        neo4j.create_audit_log(
            user_id=str(profile.pk),
            event_type=event_type,
            description=description,
            agent_id=agent_id,
            metadata=metadata,
        )
    except Exception:
        pass

    return {
        "id": str(log.pk),
        "eventType": log.event_type,
        "description": log.description,
        "agentName": log.agent.name if log.agent else None,
        "createdAt": log.created_at.isoformat() if log.created_at else "",
    }


def get_audit_log_for_user(user, event_type: str = "", limit: int = 100) -> list[dict]:
    profile = _get_profile(user)
    qs = AuditLog.objects.filter(user=profile).select_related("agent")
    if event_type:
        qs = qs.filter(event_type=event_type)
    qs = qs.order_by("-created_at")[:limit]

    return [
        {
            "id": str(log.pk),
            "eventType": log.event_type,
            "description": log.description,
            "agentName": log.agent.name if log.agent else None,
            "agentId": str(log.agent.pk) if log.agent else None,
            "createdAt": log.created_at.isoformat() if log.created_at else "",
        }
        for log in qs
    ]


def get_activity_feed_for_user(user, limit: int = 20) -> list[dict]:
    return get_audit_log_for_user(user, limit=limit)
