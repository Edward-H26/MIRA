import os

from app.users.models import UserProfile as Profile


def safe_env_bool(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def safe_env_int(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except Exception:
        return default
    return parsed if parsed > 0 else default


def safe_env_float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def get_or_create_profile(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile
