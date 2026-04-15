from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.http import HttpResponseRedirect
from django.conf import settings


class OAuthLocalhostMiddleware:
    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        if iscoroutinefunction(get_response):
            markcoroutinefunction(self)

    def _redirect_response(self, request):
        if (
            settings.DEBUG
            and request.path.startswith("/accounts/google/login")
            and "127.0.0.1" in request.get_host()
        ):
            newHost = request.get_host().replace("127.0.0.1", "localhost")
            newUrl = f"http://{newHost}{request.get_full_path()}"
            return HttpResponseRedirect(newUrl)
        return None

    def __call__(self, request):
        if iscoroutinefunction(self.get_response):
            return self.__acall__(request)
        redirect = self._redirect_response(request)
        if redirect is not None:
            return redirect
        return self.get_response(request)

    async def __acall__(self, request):
        redirect = self._redirect_response(request)
        if redirect is not None:
            return redirect
        return await self.get_response(request)
