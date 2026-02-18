from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.http import require_http_methods

from .holiday_service import (
    HolidayAPIUnavailableError,
    InvalidHolidayCountryCodeError,
    get_daily_activity_with_holidays_payload,
)
from .service import (
    get_api_analytics_summary_payload,
    get_api_daily_active_users_payload,
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
def api_public_daily_active_users(request):
    return JsonResponse(get_api_daily_active_users_payload())


@require_http_methods(["GET"])
def api_public_daily_active_users_with_holidays(request):
    country_param = request.GET.get("country", request.GET.get("q", "US"))
    pretty_json = {"indent": 2}

    try:
        payload = get_daily_activity_with_holidays_payload(
            country_code=country_param,
        )
        return JsonResponse(payload, json_dumps_params=pretty_json)
    except InvalidHolidayCountryCodeError as exc:
        return JsonResponse(
            {
                "error": "invalid_country_code",
                "requested_country_code": exc.country_code,
                "available_regions": exc.available_regions,
            },
            status=400,
            json_dumps_params=pretty_json,
        )
    except HolidayAPIUnavailableError as exc:
        return JsonResponse(
            {
                "error": "holiday_api_unavailable",
                "message": str(exc),
            },
            status=503,
            json_dumps_params=pretty_json,
        )
