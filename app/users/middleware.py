from urllib.parse import unquote
from zoneinfo import ZoneInfo

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.utils import timezone


class TimezoneMiddleware:
    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        if iscoroutinefunction(get_response):
            markcoroutinefunction(self)

    def _activate(self, request):
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

    def __call__(self, request):
        if iscoroutinefunction(self.get_response):
            return self.__acall__(request)
        self._activate(request)
        return self.get_response(request)

    async def __acall__(self, request):
        self._activate(request)
        return await self.get_response(request)
