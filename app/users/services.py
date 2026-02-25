from django.contrib.auth import login
from django.contrib.auth.models import User as AuthUser
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

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

    user = AuthUser.objects.filter(email__iexact=normalized_email).first()
    if user is None:
        return None, {"login": "Invalid email or password."}
    user = authenticate(request, username=user.username, password=password)
    if user is None:
        return None, {"login": "Invalid email or password."}
    login(request, user)
    return user, None

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
