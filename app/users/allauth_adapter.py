from django.http import HttpResponseRedirect
from django.conf import settings


class OAuthLocalhostMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            settings.DEBUG
            and request.path.startswith("/accounts/google/login")
            and "127.0.0.1" in request.get_host()
        ):
            newHost = request.get_host().replace("127.0.0.1", "localhost")
            newUrl = f"http://{newHost}{request.get_full_path()}"
            return HttpResponseRedirect(newUrl)
        return self.get_response(request)
