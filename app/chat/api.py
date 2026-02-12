from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.http import require_http_methods

from .service import (
    get_api_analytics_summary_payload,
    get_api_memory_bullets_payload,
    get_api_messages_payload,
    get_api_sessions_payload,
)


@login_required(login_url="/")
@require_http_methods(["GET"])
def api_memory_bullets(request):
    payload = get_api_memory_bullets_payload(
        request.user,
        q=request.GET.get("q", ""),
        memory_type=request.GET.get("type", ""),
        topic=request.GET.get("topic", ""),
        strength_min=request.GET.get("strength_min", ""),
    )
    return JsonResponse(payload)


@login_required(login_url="/")
@require_http_methods(["GET"])
def api_analytics_summary(request):
    return JsonResponse(get_api_analytics_summary_payload(request.user))


@method_decorator(login_required(login_url="/"), name="dispatch")
@method_decorator(require_http_methods(["GET"]), name="dispatch")
class SessionAPIView(View):
    def get(self, request):
        return JsonResponse(
            get_api_sessions_payload(request.user, q=request.GET.get("q", ""))
        )


@method_decorator(login_required(login_url="/"), name="dispatch")
@method_decorator(require_http_methods(["GET"]), name="dispatch")
class MessageAPIView(View):
    def get(self, request, session_id):
        payload = get_api_messages_payload(
            request.user,
            session_id,
            role_filter=request.GET.get("role", ""),
        )
        return JsonResponse(payload)


@require_http_methods(["GET"])
def api_demo_response(request):
    sample = {"project": "MEMORIA", "version": "1.0", "description": "Memory Enhanced AI Assistant"}
    fmt = request.GET.get("format", "json").strip()
    if fmt == "html":
        return HttpResponse(
            "<html><body><h1>MEMORIA API</h1><p>This response uses text/html MIME type.</p></body></html>",
            content_type="text/html",
        )
    if fmt == "text":
        return HttpResponse(
            "MEMORIA API: Memory Enhanced AI Assistant (text/plain MIME type)",
            content_type="text/plain",
        )
    return JsonResponse(sample)
