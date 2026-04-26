from pathlib import Path
import re
from urllib.parse import urlparse

import requests
from allauth.account.signals import user_signed_up
from django.contrib.auth.models import User as AuthUser
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models.signals import post_delete, post_save
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
    try:
        profile.profile_img.save(filename, ContentFile(response.content), save=True)
    except (OSError, IOError, ValueError) as exc:
        try:
            from memoria.event_log import log_event
            log_event(
                "google_avatar_save_failed",
                profile_pk=str(profile.pk),
                error_type=exc.__class__.__name__,
                error=str(exc)[:200],
            )
        except Exception:
            pass


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
    base_name = _build_google_username(extra_data)
    display_name = _capitalize_first(
        extra_data.get("name")
        or extra_data.get("given_name")
        or base_name
    )

    for _ in range(20):
        desired_username = _build_unique_username(base_name, user.id)
        if user.username == desired_username:
            break
        user.username = desired_username
        try:
            with transaction.atomic():
                user.save(update_fields=["username"])
            break
        except IntegrityError:
            continue

    profile, _ = UserProfile.objects.get_or_create(user=user)
    if display_name and profile.display_name != display_name:
        profile.display_name = display_name
        profile.save(update_fields=["display_name"])
    return profile


@receiver(post_save, sender=UserProfile)
def ensure_default_agent_on_profile_save(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        from app.chat.models.agent import Agent
        if not Agent.objects.filter(user=instance).exists():
            ownerUser = instance.user
            displayName = getattr(instance, "display_name", "") or ownerUser.get_full_name() or ownerUser.username
            Agent.objects.create(
                user=instance,
                name=f"{displayName}'s Agent",
                temperature=0.7,
                max_tokens=1024,
            )
    except Exception as exc:
        try:
            from memoria.event_log import log_event
            log_event(
                "default_agent_create_failed",
                profile_pk=str(instance.pk),
                error_type=exc.__class__.__name__,
                error=str(exc)[:200],
            )
        except Exception:
            pass


@receiver(user_signed_up)
def sync_google_avatar_on_signup(request, user, sociallogin=None, **kwargs):
    if sociallogin is None:
        return
    if sociallogin.account.provider != "google":
        return
    profile = _sync_google_user_names(user, sociallogin.account.extra_data or {})
    picture_url = sociallogin.account.extra_data.get("picture")
    _save_google_avatar(profile, picture_url)


@receiver(post_delete, sender=UserProfile)
def cascade_delete_neo4j_on_profile_delete(sender, instance, **kwargs):
    """When a Django UserProfile is deleted, also delete the corresponding
    Neo4j User node and every node it owns. Without this, the graph accumulates
    orphan Agents, Sessions, Messages, and Memory data forever."""
    try:
        from app.services import neo4j_memory as neo4j
        from memoria.event_log import log_event
    except Exception:
        return
    try:
        summary = neo4j.delete_user_cascade(str(instance.pk))
        log_event(
            "neo4j_user_cascade_deleted",
            profile_pk=str(instance.pk),
            **{k: int(v or 0) for k, v in (summary or {}).items()},
        )
    except Exception as exc:
        try:
            log_event(
                "neo4j_user_cascade_failed",
                profile_pk=str(instance.pk),
                error=str(exc)[:300],
            )
        except Exception:
            pass
