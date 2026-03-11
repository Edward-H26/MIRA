from memoria.event_log import is_dev_event_log_enabled, log_event


class PageVisitEventMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not is_dev_event_log_enabled():
            return response
        if request.method != "GET":
            return response
        content_type = response.get("Content-Type", "")
        if "text/html" not in content_type:
            return response
        if response.status_code >= 400:
            return response

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
        return response
