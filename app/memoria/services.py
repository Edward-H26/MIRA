from app.chat.models import Memory, Session
from app.users.models import User as Profile


def _get_or_create_profile_for_user(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


def get_home_context_for_user(user):
    profile = _get_or_create_profile_for_user(user)
    return {
        "username": user.username,
        "sessions": Session.objects.filter(user=profile).order_by("-created_at"),
        "memories": Memory.objects.filter(user=profile).order_by("-updated_at"),
    }


def create_home_session_for_user(user, content):
    profile = _get_or_create_profile_for_user(user)
    return Session.create_with_opening_exchange(profile, content)

