from asgiref.sync import iscoroutinefunction, markcoroutinefunction

from memoria.event_log import is_dev_event_log_enabled, log_event


class PageVisitEventMiddleware:
    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        if iscoroutinefunction(get_response):
            markcoroutinefunction(self)

    def __call__(self, request):
        if iscoroutinefunction(self.get_response):
            return self.__acall__(request)
        response = self.get_response(request)
        self._emit(request, response)
        return response

    async def __acall__(self, request):
        response = await self.get_response(request)
        self._emit(request, response)
        return response

    def _emit(self, request, response):
        if not is_dev_event_log_enabled():
            return
        if request.method != "GET":
            return
        content_type = response.get("Content-Type", "")
        if "text/html" not in content_type:
            return
        if response.status_code >= 400:
            return
        route_name = ""
        match = getattr(request, "resolver_match", None)
        if match is not None:
            route_name = match.view_name or ""
        log_event(
            "page_enter",
            request=request,
            status_code=response.status_code,
            route_name=route_name,
        )
