from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from . import services
from .models import User as Profile

@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.method == "GET":
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return render(request, "users/login_form.html")
        return redirect("memoria:home")
    username = request.POST.get("username", "").strip()
    password = request.POST.get("password", "")
    user, error = services.authenticate_and_login(request, username, password)
    if error:
        return render(request, "users/login_form.html", {"error": error}, status=400)
    next_url = request.POST.get("next") or "/"
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "redirect_url": next_url})
    return redirect(next_url)


@require_http_methods(["GET", "POST"])
def logout_view(request):
    if request.method == "POST":
        logout(request)
    next_url = request.POST.get("next") or "/"
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
    user, error = services.register_and_login(request, username, password1, password2)
    if error:
        return render(
            request,
            "users/register_form.html",
            {"error": error},
            status=400,
        )
    next_url = request.POST.get("next") or "/"
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "redirect_url": next_url})
    return redirect(next_url)


@login_required(login_url="/")
@require_http_methods(["GET", "POST"])
def profile_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        if request.user.email != email:
            request.user.email = email
            request.user.save(update_fields=["email"])
        profile_img = request.FILES.get("profile_img")
        if profile_img:
            if profile.profile_img:
                profile.profile_img.delete(save=False)
            profile.profile_img = profile_img
            profile.save(update_fields=["profile_img"])
        return render(
            request,
            "users/profile.html",
            {
                "profile": profile,
                "username": request.user.username,
                "email": request.user.email,
                "success": True,
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
