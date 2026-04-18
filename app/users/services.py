from django.contrib.auth import login
from django.contrib.auth.models import User as AuthUser
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction

from app.services import neo4j_memory as neo4j
from .models import UserProfile

def validate_registration(username, email, password1, password2):
    errors = {}
    if not username:
        errors["username"] = "Username is required."
    elif AuthUser.objects.filter(username=username).exists():
        errors["username"] = "Username already exists."
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        errors["email"] = "Email is required."
    else:
        try:
            validate_email(normalized_email)
        except ValidationError:
            errors["email"] = "Please enter a valid email address."
        else:
            if AuthUser.objects.filter(email__iexact=normalized_email).exists():
                errors["email"] = "Email already exists."
    if not password1:
        errors["password1"] = "Password is required."
    if not password2:
        errors["password2"] = "Please confirm your password."
    elif password1 and password1 != password2:
        errors["password2"] = "Passwords do not match."
    return errors or None


def authenticate_and_login(request, email, password):
    errors = {}
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        errors["email"] = "Email is required."
    else:
        try:
            validate_email(normalized_email)
        except ValidationError:
            errors["email"] = "Please enter a valid email address."
    if not password:
        errors["password"] = "Password is required."
    if errors:
        return None, errors

    user = _resolve_user_by_email(normalized_email)
    if user is None:
        return None, {"login": "Invalid email or password."}
    user = authenticate(request, username=user.username, password=password)
    if user is None:
        return None, {"login": "Invalid email or password."}
    login(request, user)
    return user, None


def _resolve_user_by_email(normalized_email):
    """Resolve a Django User by email using Neo4j as the source of truth.

    Neo4j stores the authoritative account record (email, username, passwordHash,
    id). Django's auth plumbing still needs a concrete User row for session and
    request.user binding, so we mirror the Neo4j record into Django lazily. The
    UserProfile primary key is aligned with the Neo4j User id so that analytics
    queries keyed on profile.pk resolve to the same graph data.
    """
    neo_user = neo4j.get_user_by_email(normalized_email)
    if neo_user is None:
        return AuthUser.objects.filter(email__iexact=normalized_email).first()
    username = neo_user.get("username") or ""
    neo_id = str(neo_user.get("id") or "")
    if not username or not neo_id:
        return None

    user = AuthUser.objects.filter(username=username).first()
    if user is None:
        try:
            with transaction.atomic():
                user = AuthUser.objects.create(
                    username=username,
                    email=neo_user.get("email") or normalized_email,
                )
                user.set_unusable_password()
                user.save(update_fields=["password"])
        except IntegrityError:
            user = AuthUser.objects.filter(username=username).first()
            if user is None:
                return None

    try:
        profile_pk = int(neo_id)
    except (ValueError, TypeError):
        profile_pk = None
    if profile_pk is not None:
        existing = UserProfile.objects.filter(pk=profile_pk).first()
        if existing is None:
            try:
                with transaction.atomic():
                    UserProfile.objects.create(
                        pk=profile_pk,
                        user=user,
                        display_name=username,
                    )
            except IntegrityError:
                UserProfile.objects.get_or_create(
                    user=user, defaults={"display_name": username}
                )
        elif existing.user_id != user.id:
            UserProfile.objects.get_or_create(
                user=user, defaults={"display_name": username}
            )
    else:
        UserProfile.objects.get_or_create(
            user=user, defaults={"display_name": username}
        )
    return user

def create_user_with_profile(username, email, password):
    normalized_email = (email or "").strip().lower()
    user = AuthUser.objects.create_user(username=username, email=normalized_email, password=password)
    UserProfile.objects.create(user=user, display_name=username)
    return user

def register_and_login(request, username, email, password1, password2):
    errors = validate_registration(username, email, password1, password2)
    if errors:
        return None, errors
    user = create_user_with_profile(username=username, email=email, password=password1)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return user, None


def get_or_create_profile_for_user(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    if not profile.display_name:
        profile.display_name = user.username
        profile.save(update_fields=["display_name"])
    return profile
