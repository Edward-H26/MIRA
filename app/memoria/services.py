from app.chat.models import Memory, Session
from app.chat.utils import get_or_create_profile


def get_home_context_for_user(user):
    profile = get_or_create_profile(user)
    return {
        "username": user.username,
        "sessions": Session.objects.filter(user=profile).order_by("-created_at"),
        "memories": Memory.objects.filter(user=profile).order_by("-updated_at"),
    }


def create_home_session_for_user(user, content):
    profile = get_or_create_profile(user)
    prompt = (content or "").strip()
    if not prompt:
        return None
    return Session.objects.create(user=profile, title=prompt[:200])

