from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.template import loader

from .services import create_home_session_for_user, get_home_context_for_user

PENDING_PROMPT_SESSION_KEY = "pending_chat_prompts"


def home(request):
    template = loader.get_template("memoria/home.html")

    if not request.user.is_authenticated:
        return redirect("memoria:landing")

    if request.method == "POST":
        content = request.POST.get("message", "").strip()
        if not content:
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"error": "Empty message"}, status=400)
            return redirect("memoria:home")
        session = create_home_session_for_user(request.user, content)
        if session is None:
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"error": "Unable to create session"}, status=400)
            return redirect("memoria:home")
        pending_prompts = dict(request.session.get(PENDING_PROMPT_SESSION_KEY, {}))
        pending_prompts[str(session.pk)] = content
        request.session[PENDING_PROMPT_SESSION_KEY] = pending_prompts
        request.session.modified = True
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({
                "session_id": session.pk,
                "redirect_url": session.get_absolute_url(),
            })
        return redirect(session.get_absolute_url())

    context = get_home_context_for_user(request.user)
    return HttpResponse(template.render(context, request))


def landing(request):
    template = loader.get_template("memoria/landing.html")
    return HttpResponse(template.render({}, request))


def not_found_view(request, exception):
    return redirect("memoria:home")
