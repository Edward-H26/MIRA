from django.http import HttpResponse
from django.shortcuts import redirect
from django.template import loader

from app.chat.service import create_home_session_for_user, get_home_context_for_user


def home(request):
    template = loader.get_template("memoria/home.html")

    if request.method == "POST":
        if not request.user.is_authenticated:
            return redirect("memoria:landing")

        content = request.POST.get("message", "").strip()
        if not content:
            return redirect("memoria:home")
        session = create_home_session_for_user(request.user, content)
        if session is None:
            return redirect("memoria:home")
        return redirect(session.get_absolute_url())

    if request.user.is_authenticated:
        context = get_home_context_for_user(request.user)
    else:
        context = {"username": "Guest", "sessions": [], "memories": []}
    return HttpResponse(template.render(context, request))


def landing(request):
    template = loader.get_template("memoria/landing.html")
    return HttpResponse(template.render({}, request))


def not_found_view(request, exception):
    return redirect("memoria:home")
