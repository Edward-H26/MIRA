from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.http import require_http_methods
from django.views.generic import DetailView, ListView

from .models import Memory, MemoryBullet
from .service import (
    create_user_message_with_agent_reply,
    get_analytics_dashboard_context,
    get_or_create_profile_for_user,
    get_memory_list_data,
    get_memory_strength_chart_png,
    get_memory_summary,
    get_memory_type_chart_png,
    get_activity_chart_png,
    get_session_for_user,
)


@method_decorator(login_required(login_url="/"), name="dispatch")
class MemoryListView(ListView):
    model = MemoryBullet
    template_name = "chat/memory.html"
    context_object_name = "bullets"

    def post(self, request, *args, **kwargs):
        return self.get(request, *args, **kwargs)

    def get_queryset(self):
        search_query = (self.request.POST.get("q") or self.request.GET.get("q") or "").strip()
        memory_type = (self.request.POST.get("type") or self.request.GET.get("type") or "").strip()
        sort_key = (self.request.POST.get("sort") or self.request.GET.get("sort") or "created").strip()
        payload = get_memory_list_data(
            self.request.user,
            search_query=search_query,
            memory_type=memory_type,
            sort_key=sort_key,
        )
        self._list_payload = payload
        return payload["queryset"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "memory_type_choices": self._list_payload["memory_type_choices"],
            "active_memory_type": self._list_payload["active_memory_type"],
            "search_query": self._list_payload["search_query"],
            "sort_label": self._list_payload["sort_label"],
            "active_sort": self._list_payload["active_sort"],
        })
        context.update(get_memory_summary(self.request.user))
        return context


@method_decorator(login_required(login_url="/"), name="dispatch")
class ConversationMessagesView(View):
    def get(self, request, session_id):
        session = get_session_for_user(request.user, session_id, with_messages=True)
        return render(request, "chat/conversation_detail.html", {"session": session})

    def post(self, request, session_id):
        session = get_session_for_user(request.user, session_id)

        content = (request.POST.get("message") or "").strip()
        if content:
            create_user_message_with_agent_reply(session, content)

        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            if not content:
                return JsonResponse({"error": "Empty message"}, status=400)
            return JsonResponse({
                "messages": [
                    {"role": "user", "content": content},
                    {"role": "assistant", "content": "Agent Response"},
                ],
                "session_id": session.pk,
            })

        return redirect(session.get_absolute_url())


@method_decorator(login_required(login_url="/"), name="dispatch")
class MemoryBulletsView(DetailView):
    model = Memory
    template_name = "chat/memory_detail.html"
    context_object_name = "memory"
    pk_url_kwarg = "memory_id"

    def get_queryset(self):
        profile = get_or_create_profile_for_user(self.request.user)
        return (
            Memory.objects.filter(user=profile)
            .prefetch_related("memorybullet_set")
            .order_by("-updated_at")
        )


@login_required(login_url="/")
@require_http_methods(["POST"])
def session_rename_view(request, session_id):
    session = get_session_for_user(request.user, session_id)
    title = (request.POST.get("title") or "").strip()
    if title:
        session.title = title[:200]
        session.save(update_fields=["title"])
    return JsonResponse({"ok": True, "title": session.title})


@login_required(login_url="/")
@require_http_methods(["POST"])
def session_delete_view(request, session_id):
    session = get_session_for_user(request.user, session_id)
    session.delete()
    return JsonResponse({"ok": True})


@login_required(login_url="/")
def analytics_view(request):
    return render(request, "chat/analytics.html", get_analytics_dashboard_context(request.user))


@login_required(login_url="/")
@require_http_methods(["GET"])
def memory_type_chart_png(request):
    return HttpResponse(get_memory_type_chart_png(request.user), content_type="image/png")


@login_required(login_url="/")
@require_http_methods(["GET"])
def memory_strength_chart_png(request):
    return HttpResponse(get_memory_strength_chart_png(request.user), content_type="image/png")


@login_required(login_url="/")
@require_http_methods(["GET"])
def activity_chart_png(request):
    return HttpResponse(get_activity_chart_png(request.user), content_type="image/png")


