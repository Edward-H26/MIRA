from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import DetailView

from app.users.models import User as Profile

from django.db.models import Prefetch

from .models import Memory, Message, Session


def chat_view(request):
    return render(request, "chat/chat.html")


def memory_view(request):
    return render(request, "chat/memory.html")


@method_decorator(login_required(login_url="/"), name="dispatch")
class ConversationMessagesView(View):
    def get(self, request, session_id):
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


@method_decorator(login_required(login_url="/"), name="dispatch")
class MemoryBulletsView(DetailView):
    model = Memory
    template_name = "chat/memory_detail.html"
    context_object_name = "memory"
    pk_url_kwarg = "memory_id"

    def get_queryset(self):
        profile, _ = Profile.objects.get_or_create(user=self.request.user)
        return (
            Memory.objects.filter(user=profile)
            .prefetch_related("memorybullet_set")
            .order_by("-updated_at")
        )
