import io
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, ExpressionWrapper, F, IntegerField, Max, Min, Prefetch, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.http import require_http_methods
from django.views.generic import DetailView, ListView
from django.apps import apps

from .models import Memory, Message, MemoryBullet, Session
from .service import create_user_message_with_agent_reply


def _get_profile(request):
    Profile = apps.get_model("users", "User")
    profile, _ = Profile.objects.get_or_create(user=request.user)
    return profile


def chat_view(request):
    return render(request, "chat/chat.html")


@method_decorator(login_required(login_url="/"), name="dispatch")
class MemoryListView(ListView):
    model = MemoryBullet
    template_name = "chat/memory.html"
    context_object_name = "bullets"

    def post(self, request, *args, **kwargs):
        return self.get(request, *args, **kwargs)

    def get_queryset(self):
        profile = _get_profile(self.request)
        bullets = MemoryBullet.objects.select_related("memory").filter(memory__user=profile)

        search_query = (self.request.POST.get("q") or self.request.GET.get("q") or "").strip()
        memory_type = (self.request.POST.get("type") or self.request.GET.get("type") or "").strip()
        sort_key = (self.request.POST.get("sort") or self.request.GET.get("sort") or "created").strip()

        self._search_query = search_query
        self._memory_type = memory_type
        self._sort_key = sort_key

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
        self._sort_label = sort_label
        self._sort_key_resolved = sort_key if sort_key in sort_map else "created"
        return bullets.order_by(sort_order, "-last_accessed")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        profile = _get_profile(self.request)
        all_user_bullets = MemoryBullet.objects.filter(memory__user=profile)

        total_count = all_user_bullets.count()

        type_summary_raw = (
            all_user_bullets
            .values("memory_type")
            .annotate(count=Count("id"))
            .order_by("memory_type")
        )
        type_choices = dict(MemoryBullet._meta.get_field("memory_type").choices)
        type_summary = [
            {"memory_type": item["memory_type"], "label": type_choices.get(item["memory_type"], str(item["memory_type"])), "count": item["count"]}
            for item in type_summary_raw
        ]

        agg = all_user_bullets.aggregate(
            avg_strength=Avg("strength"),
            max_strength=Max("strength"),
            min_strength=Min("strength"),
            total_helpful=Sum("helpful_count"),
            total_harmful=Sum("harmful_count"),
        )

        context.update({
            "memory_type_choices": MemoryBullet._meta.get_field("memory_type").choices,
            "active_memory_type": self._memory_type,
            "search_query": self._search_query,
            "sort_label": self._sort_label,
            "active_sort": self._sort_key_resolved,
            "total_count": total_count,
            "type_summary": type_summary,
            "avg_strength": agg["avg_strength"],
            "max_strength": agg["max_strength"],
            "min_strength": agg["min_strength"],
            "total_helpful": agg["total_helpful"] or 0,
            "total_harmful": agg["total_harmful"] or 0,
        })
        return context


@method_decorator(login_required(login_url="/"), name="dispatch")
class ConversationMessagesView(View):
    def get(self, request, session_id):
        profile = _get_profile(request)
        messages_prefetch = Prefetch(
            "messages",
            queryset=Message.objects.order_by("created_at"),
        )
        session = get_object_or_404(
            Session.objects.filter(user=profile).prefetch_related(messages_prefetch),
            pk=session_id,
        )
        return render(request, "chat/conversation_detail.html", {"session": session})

    def post(self, request, session_id):
        profile = _get_profile(request)
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
        profile = _get_profile(self.request)
        return (
            Memory.objects.filter(user=profile)
            .prefetch_related("memorybullet_set")
            .order_by("-updated_at")
        )


@login_required(login_url="/")
@require_http_methods(["POST"])
def session_rename_view(request, session_id):
    profile = _get_profile(request)
    session = get_object_or_404(Session, pk=session_id, user=profile)
    title = (request.POST.get("title") or "").strip()
    if title:
        session.title = title[:200]
        session.save(update_fields=["title"])
    return JsonResponse({"ok": True, "title": session.title})


@login_required(login_url="/")
@require_http_methods(["POST"])
def session_delete_view(request, session_id):
    profile = _get_profile(request)
    session = get_object_or_404(Session, pk=session_id, user=profile)
    session.delete()
    return JsonResponse({"ok": True})


@login_required(login_url="/")
def analytics_view(request):
    profile = _get_profile(request)
    bullets = MemoryBullet.objects.filter(memory__user=profile)
    sessions = Session.objects.filter(user=profile)

    total_memories = bullets.count()
    total_sessions = sessions.count()
    total_messages = Message.objects.filter(session__user=profile).count()

    type_choices = dict(MemoryBullet._meta.get_field("memory_type").choices)
    type_data = list(
        bullets.values("memory_type")
        .annotate(count=Count("id"))
        .order_by("memory_type")
    )
    type_summary = [
        {"label": type_choices.get(d["memory_type"], str(d["memory_type"])), "count": d["count"]}
        for d in type_data
    ]

    agg = bullets.aggregate(avg_strength=Avg("strength"))

    return render(request, "chat/analytics.html", {
        "total_memories": total_memories,
        "total_sessions": total_sessions,
        "total_messages": total_messages,
        "avg_strength": agg["avg_strength"],
        "type_summary": type_summary,
    })


def _render_chart_to_response(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return HttpResponse(buf.getvalue(), content_type="image/png")


@login_required(login_url="/")
def memory_type_chart_png(request):
    profile = _get_profile(request)
    type_data = (
        MemoryBullet.objects
        .filter(memory__user=profile)
        .values("memory_type")
        .annotate(count=Count("id"))
        .order_by("memory_type")
    )
    type_choices = dict(MemoryBullet._meta.get_field("memory_type").choices)
    labels = [type_choices.get(d["memory_type"], str(d["memory_type"])) for d in type_data]
    counts = [d["count"] for d in type_data]

    colors = ["#a78bfa", "#93c5fd", "#f9a8d4", "#86efac", "#fde68a"]
    fig, ax = plt.subplots(figsize=(7, 5))
    if labels:
        ax.pie(counts, labels=labels, autopct="%1.1f%%", colors=colors[:len(labels)], startangle=140)
        ax.set_title("Memory Type Distribution", fontsize=14, fontweight="bold", pad=16)
    else:
        ax.text(0.5, 0.5, "No memory data yet", ha="center", va="center", fontsize=14, color="#999")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

    fig.patch.set_facecolor("#fafafa")
    return _render_chart_to_response(fig)


@login_required(login_url="/")
def memory_strength_chart_png(request):
    profile = _get_profile(request)
    bullets = MemoryBullet.objects.filter(memory__user=profile).values_list("strength", flat=True)
    strengths = list(bullets)

    buckets = {"0-20": 0, "21-40": 0, "41-60": 0, "61-80": 0, "81-100": 0}
    for s in strengths:
        if s <= 20:
            buckets["0-20"] += 1
        elif s <= 40:
            buckets["21-40"] += 1
        elif s <= 60:
            buckets["41-60"] += 1
        elif s <= 80:
            buckets["61-80"] += 1
        else:
            buckets["81-100"] += 1

    fig, ax = plt.subplots(figsize=(7, 5))
    colors = ["#fca5a5", "#fdba74", "#fde68a", "#86efac", "#6ee7b7"]
    if strengths:
        ax.bar(buckets.keys(), buckets.values(), color=colors)
        ax.set_title("Memory Strength Distribution", fontsize=14, fontweight="bold", pad=16)
        ax.set_xlabel("Strength Range")
        ax.set_ylabel("Count")
    else:
        ax.text(0.5, 0.5, "No memory data yet", ha="center", va="center", fontsize=14, color="#999")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

    fig.patch.set_facecolor("#fafafa")
    return _render_chart_to_response(fig)


@login_required(login_url="/")
def activity_chart_png(request):
    profile = _get_profile(request)
    thirty_days_ago = timezone.now() - timezone.timedelta(days=30)
    daily = (
        Session.objects.filter(user=profile, created_at__gte=thirty_days_ago)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )

    fig, ax = plt.subplots(figsize=(8, 4))
    if daily:
        days = [d["day"].strftime("%m/%d") for d in daily]
        counts = [d["count"] for d in daily]
        ax.plot(days, counts, marker="o", color="#8b5cf6", linewidth=2, markersize=5)
        ax.fill_between(range(len(days)), counts, alpha=0.15, color="#8b5cf6")
        ax.set_xticks(range(len(days)))
        ax.set_xticklabels(days, rotation=45, ha="right", fontsize=8)
        ax.set_title("Conversation Activity (Last 30 Days)", fontsize=14, fontweight="bold", pad=16)
        ax.set_xlabel("Date")
        ax.set_ylabel("Sessions Created")
    else:
        ax.text(0.5, 0.5, "No activity data yet", ha="center", va="center", fontsize=14, color="#999")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

    fig.patch.set_facecolor("#fafafa")
    fig.tight_layout()
    return _render_chart_to_response(fig)


@login_required(login_url="/")
def api_memory_bullets(request):
    profile = _get_profile(request)
    bullets = MemoryBullet.objects.select_related("memory").filter(memory__user=profile)

    q = request.GET.get("q", "").strip()
    if q:
        bullets = bullets.filter(content__icontains=q)

    memory_type = request.GET.get("type", "").strip()
    if memory_type.isdigit():
        bullets = bullets.filter(memory_type=int(memory_type))

    topic = request.GET.get("topic", "").strip()
    if topic:
        bullets = bullets.filter(topic__icontains=topic)

    strength_min = request.GET.get("strength_min", "").strip()
    if strength_min.isdigit():
        bullets = bullets.filter(strength__gte=int(strength_min))

    data = [
        {
            "id": b.id,
            "content": b.content,
            "memory_type": b.get_memory_type_display(),
            "topic": b.topic,
            "strength": b.strength,
            "helpful_count": b.helpful_count,
            "harmful_count": b.harmful_count,
            "created_at": b.created_at.isoformat(),
            "last_accessed": b.last_accessed.isoformat(),
        }
        for b in bullets[:100]
    ]
    return JsonResponse({"count": len(data), "results": data})


@login_required(login_url="/")
def api_analytics_summary(request):
    profile = _get_profile(request)
    bullets = MemoryBullet.objects.filter(memory__user=profile)
    sessions = Session.objects.filter(user=profile)

    type_dist = list(
        bullets.values("memory_type")
        .annotate(count=Count("id"))
        .order_by("memory_type")
    )
    agg = bullets.aggregate(
        avg_strength=Avg("strength"),
        total_helpful=Sum("helpful_count"),
        total_harmful=Sum("harmful_count"),
    )
    return JsonResponse({
        "total_memories": bullets.count(),
        "total_sessions": sessions.count(),
        "type_distribution": type_dist,
        "avg_strength": agg["avg_strength"],
        "total_helpful": agg["total_helpful"] or 0,
        "total_harmful": agg["total_harmful"] or 0,
    })


class SessionAPIView(View):
    def get(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=401)
        profile = _get_profile(request)
        sessions = Session.objects.filter(user=profile)

        q = request.GET.get("q", "").strip()
        if q:
            sessions = sessions.filter(title__icontains=q)

        data = [
            {
                "id": s.id,
                "title": s.title,
                "created_at": s.created_at.isoformat(),
                "updated_at": s.updated_at.isoformat(),
                "url": s.get_absolute_url(),
            }
            for s in sessions[:50]
        ]
        return JsonResponse({"count": len(data), "results": data})


class MessageAPIView(View):
    def get(self, request, session_id):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=401)
        profile = _get_profile(request)
        session = get_object_or_404(Session, pk=session_id, user=profile)
        messages = session.messages.order_by("created_at")

        role_filter = request.GET.get("role", "").strip()
        if role_filter.isdigit():
            messages = messages.filter(role=int(role_filter))

        data = [
            {
                "id": m.id,
                "role": m.get_role_display(),
                "content": m.content,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ]
        return JsonResponse({"session_id": session_id, "count": len(data), "messages": data})


def api_demo_response(request):
    sample = {"project": "MEMORIA", "version": "1.0", "description": "Memory Enhanced AI Assistant"}
    fmt = request.GET.get("format", "json").strip()
    if fmt == "html":
        return HttpResponse(
            "<html><body><h1>MEMORIA API</h1><p>This response uses text/html MIME type.</p></body></html>",
            content_type="text/html",
        )
    if fmt == "text":
        return HttpResponse(
            "MEMORIA API: Memory Enhanced AI Assistant (text/plain MIME type)",
            content_type="text/plain",
        )
    return JsonResponse(sample)
