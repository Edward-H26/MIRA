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

    result = neo4j.create_audit_log(
        user_id=str(profile.pk),
        event_type=event_type,
        description=description,
        agent_id=agent_id,
        metadata=metadata,
    )

    return {
        "id": result.get("id", ""),
        "eventType": result.get("eventType", ""),
        "description": result.get("description", ""),
        "agentName": result.get("agentName"),
        "createdAt": result.get("createdAt", ""),
    }


def get_audit_log_for_user(user, event_type: str = "", limit: int = 100) -> list[dict]:
    profile = _get_profile(user)

    logs = neo4j.get_audit_logs(
        user_id=str(profile.pk),
        event_type=event_type,
        limit=limit,
    )

    return [
        {
            "id": log.get("id", ""),
            "eventType": log.get("eventType", ""),
            "description": log.get("description", ""),
            "agentName": log.get("agentName"),
            "agentId": log.get("agentId"),
            "createdAt": log.get("createdAt", ""),
        }
        for log in logs
    ]


def get_activity_feed_for_user(user, limit: int = 20) -> list[dict]:
    return get_audit_log_for_user(user, limit=limit)
