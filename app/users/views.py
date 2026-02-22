from django.contrib.auth import logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.http import FileResponse
from django.http import Http404
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods
from pathlib import Path

from . import services
from .models import User as Profile


def _get_safe_redirect_url(request, fallback="/"):
    next_url = (request.POST.get("next") or "").strip()
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return fallback


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.method == "GET":
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return render(request, "users/login_form.html")
        return redirect("memoria:home")
    username = request.POST.get("username", "").strip()
    password = request.POST.get("password", "")
    user, errors = services.authenticate_and_login(request, username, password)
    if errors:
        login_error = errors.get("login", "")
        return render(
            request,
            "users/login_form.html",
            {"login_error": login_error, "username": username},
            status=400,
        )
    next_url = _get_safe_redirect_url(request, fallback="/")
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "redirect_url": next_url})
    return redirect(next_url)


@require_http_methods(["POST"])
def logout_view(request):
    logout(request)
    next_url = _get_safe_redirect_url(request, fallback="/")
    return redirect(next_url)


@require_http_methods(["GET", "POST"])
def register_view(request):
    if request.method == "GET":
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return render(request, "users/register_form.html")
        return redirect("memoria:home")
    username = request.POST.get("username", "").strip()
    password1 = request.POST.get("password1", "")
    password2 = request.POST.get("password2", "")
    user, errors = services.register_and_login(request, username, password1, password2)
    if errors:
        password_mismatch = errors.get("password2") == "Passwords do not match."
        return render(
            request,
            "users/register_form.html",
            {
                "username": username,
                "username_error": errors.get("username", ""),
                "password1_error": errors.get("password1", ""),
                "password2_error": errors.get("password2", ""),
                "password_mismatch": password_mismatch,
            },
            status=400,
        )
    next_url = _get_safe_redirect_url(request, fallback="/")
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "redirect_url": next_url})
    return redirect(next_url)


@login_required(login_url="/")
@require_http_methods(["GET", "POST"])
def profile_view(request):
    profile = services.get_or_create_profile_for_user(request.user)
    if request.method == "POST":
        email_success = False
        account_success = False
        account_error = ""
        email = request.POST.get("email", "").strip()
        if request.POST.get("save_email"):
            if request.user.email != email:
                request.user.email = email
                request.user.save(update_fields=["email"])
            email_success = True
        profile_img = request.FILES.get("profile_img")
        if profile_img and request.POST.get("save_account"):
            extension = Path(profile_img.name).suffix.lower()
            allowed_extensions = {".png", ".jpg", ".jpeg"}
            allowed_content_types = {"image/png", "image/jpeg"}
            if extension not in allowed_extensions or profile_img.content_type not in allowed_content_types:
                account_error = "Avatar must be a PNG or JPG image."
            else:
                if profile.profile_img:
                    profile.profile_img.delete(save=False)
                profile.profile_img = profile_img
                profile.save(update_fields=["profile_img"])
                account_success = True
        return render(
            request,
            "users/profile.html",
            {
                "profile": profile,
                "username": request.user.username,
                "email": request.user.email,
                "success": account_success,
                "account_error": account_error,
                "email_success": email_success,
            },
        )
    return render(
        request,
        "users/profile.html",
        {
            "profile": profile,
            "username": request.user.username,
            "email": request.user.email,
        },
    )


@login_required(login_url="/")
@require_http_methods(["GET"])
def avatar_view(request, uuid):
    profile = get_object_or_404(Profile, uuid=uuid)
    if request.user.id != profile.user_id and not request.user.is_staff:
        raise Http404()
    if not profile.profile_img:
        raise Http404()
    try:
        return FileResponse(profile.profile_img.open("rb"))
    except FileNotFoundError:
        # Clear stale DB path so future page renders use the default avatar branch.
        profile.profile_img = None
        profile.save(update_fields=["profile_img"])
        default_avatar_path = settings.BASE_DIR / "static" / "images" / "avatar.png"
        try:
            return FileResponse(open(default_avatar_path, "rb"))
        except FileNotFoundError:
            raise Http404()


@login_required(login_url="/")
@require_http_methods(["GET", "POST"])
def change_password_view(request):
    if request.method == "GET":
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return render(request, "users/password_change_form.html")
        return redirect("users:profile")
    current_password = request.POST.get("current_password", "")
    new_password = request.POST.get("new_password", "")
    confirm_password = request.POST.get("confirm_password", "")
    error = ""
    if not current_password or not new_password or not confirm_password:
        error = "Please fill out all password fields."
    elif not request.user.check_password(current_password):
        error = "Current password is incorrect."
    elif new_password != confirm_password:
        error = "New passwords do not match."
    if error:
        return render(
            request,
            "users/password_change_form.html",
            {"error": error},
            status=400,
        )
    request.user.set_password(new_password)
    request.user.save(update_fields=["password"])
    update_session_auth_hash(request, request.user)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True})
    return redirect("users:profile")
