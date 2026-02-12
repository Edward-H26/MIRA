from django.contrib.auth import login
from django.contrib.auth.models import User as AuthUser
from django.contrib.auth import authenticate

from .models import User as Profile

def validate_registration(username, password1, password2):
    errors = {}
    if not username:
        errors["username"] = "Username is required."
    elif AuthUser.objects.filter(username=username).exists():
        errors["username"] = "Username already exists."
    if not password1:
        errors["password1"] = "Password is required."
    if not password2:
        errors["password2"] = "Please confirm your password."
    elif password1 and password1 != password2:
        errors["password2"] = "Passwords do not match."
    return errors or None


def authenticate_and_login(request, username, password):
    user = authenticate(request, username=username, password=password)
    if user is None:
        return None, {"login": "Invalid username or password."}
    login(request, user)
    return user, None

def create_user_with_profile(username, password):
    user = AuthUser.objects.create_user(username=username, password=password)
    Profile.objects.create(user=user)
    return user

def register_and_login(request, username, password1, password2):
    errors = validate_registration(username, password1, password2)
    if errors:
        return None, errors
    user = create_user_with_profile(username=username, password=password1)
    login(request, user)
    return user, None


def get_or_create_profile_for_user(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile
