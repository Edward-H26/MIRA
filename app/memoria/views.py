from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.template import loader

from .services import create_home_session_for_user, get_home_context_for_user
from memoria.event_log import log_event

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
        sessionId = session.get("id", "") if isinstance(session, dict) else str(session.pk)
        sessionUrl = f"/chat/c/{sessionId}/"
        pending_prompts = dict(request.session.get(PENDING_PROMPT_SESSION_KEY, {}))
        pending_prompts[sessionId] = content
        request.session[PENDING_PROMPT_SESSION_KEY] = pending_prompts
        request.session.modified = True
        log_event(
            "chat_session_created",
            request=request,
            session_id=sessionId,
            from_page="home",
        )
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({
                "session_id": sessionId,
                "redirect_url": sessionUrl,
            })
        return redirect(sessionUrl)

    context = get_home_context_for_user(request.user)
    return HttpResponse(template.render(context, request))


def landing(request):
    template = loader.get_template("memoria/landing.html")
    return HttpResponse(template.render({}, request))


def help_view(request):
    template = loader.get_template("memoria/help.html")
    return HttpResponse(template.render({}, request))


def privacy_view(request):
    template = loader.get_template("memoria/privacy.html")
    return HttpResponse(template.render({}, request))


def not_found_view(request, exception):
    return redirect("memoria:home")
