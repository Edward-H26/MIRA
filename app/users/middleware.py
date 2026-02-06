from urllib.parse import unquote
from zoneinfo import ZoneInfo

from django.utils import timezone


class TimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        timezone_name = request.COOKIES.get("user_tz")
        if timezone_name:
            timezone_name = unquote(timezone_name)
        if timezone_name:
            try:
                timezone.activate(ZoneInfo(timezone_name))
            except Exception:
                timezone.deactivate()
        else:
            timezone.deactivate()
        return self.get_response(request)
