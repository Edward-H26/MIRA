from pathlib import Path
import re
from urllib.parse import urlparse

import requests
from allauth.account.signals import user_signed_up
from django.contrib.auth.models import User as AuthUser
from django.core.files.base import ContentFile
from django.dispatch import receiver

from .models import UserProfile


def _build_avatar_filename(picture_url):
    parsed = urlparse(picture_url or "")
    extension = Path(parsed.path).suffix.lower() or ".jpg"
    if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
        extension = ".jpg"
    return f"google_avatar{extension}"


def _save_google_avatar(profile, picture_url):
    if not picture_url or profile.profile_img:
        return
    try:
        response = requests.get(picture_url, timeout=8)
        response.raise_for_status()
    except requests.RequestException:
        return
    if not response.content:
        return
    filename = _build_avatar_filename(picture_url)
    profile.profile_img.save(filename, ContentFile(response.content), save=True)


def _capitalize_first(value):
    text = (value or "").strip()
    if not text:
        return ""
    return text[0].upper() + text[1:]


def _build_google_username(extra_data):
    raw = (
        extra_data.get("given_name")
        or extra_data.get("name")
        or (extra_data.get("email") or "").split("@", 1)[0]
        or "User"
    )
    cleaned = re.sub(r"[^\w.@+-]", "", raw)[:150]
    if not cleaned:
        cleaned = "User"
    return _capitalize_first(cleaned)


def _build_unique_username(base, user_id):
    candidate = (base or "User")[:150]
    suffix = 1
    while AuthUser.objects.filter(username=candidate).exclude(pk=user_id).exists():
        suffix_text = str(suffix)
        prefix_len = 150 - len(suffix_text)
        candidate = f"{base[:prefix_len]}{suffix_text}"
        suffix += 1
    return candidate


def _sync_google_user_names(user, extra_data):
    desired_username = _build_unique_username(_build_google_username(extra_data), user.id)
    display_name = _capitalize_first(
        extra_data.get("name")
        or extra_data.get("given_name")
        or desired_username
    )

    update_fields = []
    if user.username != desired_username:
        user.username = desired_username
        update_fields.append("username")
    if update_fields:
        user.save(update_fields=update_fields)

    profile, _ = UserProfile.objects.get_or_create(user=user)
    if not profile.display_name:
        profile.display_name = display_name
        profile.save(update_fields=["display_name"])
    return profile


@receiver(user_signed_up)
def sync_google_avatar_on_signup(request, user, sociallogin=None, **kwargs):
    if sociallogin is None:
        return
    if sociallogin.account.provider != "google":
        return
    profile = _sync_google_user_names(user, sociallogin.account.extra_data or {})
    picture_url = sociallogin.account.extra_data.get("picture")
    _save_google_avatar(profile, picture_url)
