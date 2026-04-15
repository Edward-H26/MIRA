from app.services import neo4j_memory as neo4j
from app.chat.utils import get_or_create_profile


def get_home_context_for_user(user):
    profile = get_or_create_profile(user)
    userId = str(profile.pk)
    sessions = neo4j.get_sessions_for_user(userId)
    memoryData = neo4j.get_or_create_memory(userId)
    memoryId = memoryData.get("id", "")
    bullets = neo4j.get_bullets_for_memory(memoryId, learner_id=str(profile.pk)) if memoryId else []
    return {
        "username": user.username,
        "sessions": sessions,
        "memories": bullets,
    }


def create_home_session_for_user(user, content):
    from app.chat.write_service import create_session_with_outbox
    profile = get_or_create_profile(user)
    prompt = (content or "").strip()
    if not prompt:
        return None
    session = create_session_with_outbox(str(profile.pk), prompt[:200])
    return session

