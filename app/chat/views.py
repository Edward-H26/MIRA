import re

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.apps import apps
from django.http import JsonResponse
from django.views import View
from django.views.generic import DetailView

from django.db.models import ExpressionWrapper, F, IntegerField, Prefetch

from .models import Memory, Message, MemoryBullet, Session
from .service import create_user_message_with_agent_reply


def chat_view(request):
    return render(request, "chat/chat.html")


@login_required(login_url="/")
def memory_view(request):
    Profile = apps.get_model("users", "User")
    profile, _ = Profile.objects.get_or_create(user=request.user)
    bullets = MemoryBullet.objects.select_related("memory").filter(memory__user=profile)
    search_query = (request.GET.get("q") or "").strip()
    memory_type = (request.GET.get("type") or "").strip()
    sort_key = (request.GET.get("sort") or "created").strip()
    if search_query:
        terms = [term for term in re.split(r"\s+", search_query) if term]
        for term in terms:
            bullets = bullets.filter(content__icontains=term)
    if memory_type.isdigit():
        bullets = bullets.filter(memory_type=int(memory_type))

    bullets = bullets.annotate(
        affect=ExpressionWrapper(
            F("helpful_count") - F("harmful_count"),
            output_field=IntegerField(),
        )
    )

    sort_map = {
        "created": ("-created_at", "Created time"),
        "strength": ("-strength", "Strength"),
        "affect": ("-affect", "Affect"),
    }
    sort_order, sort_label = sort_map.get(sort_key, sort_map["created"])
    bullets = bullets.order_by(sort_order, "-last_accessed")

    memory_type_choices = MemoryBullet._meta.get_field("memory_type").choices
    return render(
        request,
        "chat/memory.html",
        {
            "bullets": bullets,
            "memory_type_choices": memory_type_choices,
            "active_memory_type": memory_type,
            "search_query": search_query,
            "sort_label": sort_label,
            "active_sort": sort_key,
        },
    )


@method_decorator(login_required(login_url="/"), name="dispatch")
class ConversationMessagesView(View):
    def get(self, request, session_id):
        Profile = apps.get_model("users", "User")
        profile, _ = Profile.objects.get_or_create(user=request.user)
        messages_prefetch = Prefetch(
            "messages",
            queryset=Message.objects.order_by("created_at"),
        )
        session = get_object_or_404(
            Session.objects.filter(user=profile).prefetch_related(messages_prefetch),
            pk=session_id,
        )
        return render(
            request,
            "chat/conversation_detail.html",
            {
                "session": session,
            },
        )

    def post(self, request, session_id):
        Profile = apps.get_model("users", "User")
        profile, _ = Profile.objects.get_or_create(user=request.user)
        session = get_object_or_404(Session.objects.filter(user=profile), pk=session_id)

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
        Profile = apps.get_model("users", "User")
        profile, _ = Profile.objects.get_or_create(user=self.request.user)
        return (
            Memory.objects.filter(user=profile)
            .prefetch_related("memorybullet_set")
            .order_by("-updated_at")
        )
