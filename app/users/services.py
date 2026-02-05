from django.contrib.auth import login
from django.contrib.auth.models import User as AuthUser
from django.contrib.auth import authenticate

from .models import User as Profile

def validate_registration(username, password1, password2):
    if not username or not password1:
        return "Username and password are required."
    if password1 != password2:
        return "Passwords do not match."
    if AuthUser.objects.filter(username=username).exists():
        return "Username already exists."
    return None


def authenticate_and_login(request, username, password):
    user = authenticate(request, username=username, password=password)
    if user is None:
        return None, "Invalid username or password."
    login(request, user)
    return user, None

def create_user_with_profile(username, password):
    user = AuthUser.objects.create_user(username=username, password=password)
    Profile.objects.create(user=user)
    return user

def register_and_login(request, username, password1, password2):
    error = validate_registration(username, password1, password2)
    if error:
        return None, error
    user = create_user_with_profile(username=username, password=password1)
    login(request, user)
    return user, None
