import io
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from django.db.models import Avg, Count, ExpressionWrapper, F, IntegerField, Max, Min, Prefetch, Sum
from django.db.models.functions import TruncDate
from django.http import Http404
from django.utils import timezone

from .models import Memory, Message, MemoryBullet, Session
from .models.message import Role
from app.users.services import get_or_create_profile_for_user

PROGRESSIVE_COLORS = ["#575BEF", "#6F82FF", "#8DA0FF", "#AEBBFF", "#D6DDFF"]
SEGMENT_COLORS = ["#9698FF", "#664FA1", "#FFC5D6", "#DAC6FF", "#B4EDE4"]
CHART_BG = "#F7F8FF"
CHART_GRID = "#DCE1FF"
CHART_TEXT = "#2F3A4A"
CHART_MUTED = "#6A7290"


def _get_session_queryset_for_user(user):
    profile = get_or_create_profile_for_user(user)
    return Session.objects.filter(user=profile)


def _get_session_or_404_for_user(user, session_id, with_messages=False):
    sessions = _get_session_queryset_for_user(user)
    if with_messages:
        messages_prefetch = Prefetch(
            "messages",
            queryset=Message.objects.order_by("created_at"),
        )
        sessions = sessions.prefetch_related(messages_prefetch)
    try:
        return sessions.get(pk=session_id)
    except Session.DoesNotExist as exc:
        raise Http404 from exc


def _get_memory_bullets_queryset_for_user(user):
    profile = get_or_create_profile_for_user(user)
    return MemoryBullet.objects.select_related("memory").filter(memory__user=profile)


def _apply_memory_bullet_filters(queryset, q="", memory_type="", topic="", strength_min=""):
    normalized_q = (q or "").strip()
    normalized_memory_type = (memory_type or "").strip()
    normalized_topic = (topic or "").strip()
    normalized_strength_min = (strength_min or "").strip()

    if normalized_q:
        terms = [term for term in re.split(r"\s+", normalized_q) if term]
        for term in terms:
            queryset = queryset.filter(content__icontains=term)
    if normalized_memory_type.isdigit():
        queryset = queryset.filter(memory_type=int(normalized_memory_type))
    if normalized_topic:
        queryset = queryset.filter(topic__icontains=normalized_topic)
    if normalized_strength_min.isdigit():
        queryset = queryset.filter(strength__gte=int(normalized_strength_min))
    return queryset


def _get_analytics_metrics_for_user(user):
    profile = get_or_create_profile_for_user(user)
    bullets = MemoryBullet.objects.filter(memory__user=profile)
    sessions = Session.objects.filter(user=profile)
    messages = Message.objects.filter(session__user=profile)

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
    return {
        "total_memories": bullets.count(),
        "total_sessions": sessions.count(),
        "total_messages": messages.count(),
        "avg_strength": agg["avg_strength"],
        "total_helpful": agg["total_helpful"] or 0,
        "total_harmful": agg["total_harmful"] or 0,
        "type_distribution_raw": type_dist,
    }


def get_sidebar_sessions_for_user(user):
    return _get_session_queryset_for_user(user).order_by("-updated_at")


def get_home_context_for_user(user):
    profile = get_or_create_profile_for_user(user)
    return {
        "username": user.username,
        "sessions": _get_session_queryset_for_user(user).order_by("-created_at"),
        "memories": Memory.objects.filter(user=profile).order_by("-updated_at"),
    }


def create_home_session_for_user(user, content):
    profile = get_or_create_profile_for_user(user)
    return Session.create_with_opening_exchange(profile, content)


def get_session_for_user(user, session_id, with_messages=False):
    return _get_session_or_404_for_user(user, session_id, with_messages=with_messages)


def create_user_message_with_agent_reply(session, content):
    trimmed = (content or "").strip()
    if not trimmed:
        return False

    Message.objects.create(
        session=session,
        role=Role.USER,
        content=trimmed,
    )
    Message.objects.create(
        session=session,
        role=Role.ASSISTANT,
        content="Agent Response",
    )
    session.updated_at = timezone.now()
    session.save(update_fields=["updated_at"])
    return True


def get_memory_list_data(user, search_query="", memory_type="", sort_key="created"):
    bullets = _get_memory_bullets_queryset_for_user(user)

    query = (search_query or "").strip()
    memory_type = (memory_type or "").strip()
    sort_key = (sort_key or "created").strip()

    bullets = _apply_memory_bullet_filters(
        bullets,
        q=query,
        memory_type=memory_type,
    )

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
    active_sort = sort_key if sort_key in sort_map else "created"

    return {
        "queryset": bullets.order_by(sort_order, "-last_accessed"),
        "active_memory_type": memory_type,
        "search_query": query,
        "sort_label": sort_label,
        "active_sort": active_sort,
        "memory_type_choices": MemoryBullet._meta.get_field("memory_type").choices,
    }


def get_memory_summary(user):
    profile = get_or_create_profile_for_user(user)
    bullets = MemoryBullet.objects.filter(memory__user=profile)

    type_summary_raw = (
        bullets.values("memory_type")
        .annotate(count=Count("id"))
        .order_by("memory_type")
    )
    type_choices = dict(MemoryBullet._meta.get_field("memory_type").choices)
    type_summary = [
        {"memory_type": item["memory_type"], "label": type_choices.get(item["memory_type"], str(item["memory_type"])), "count": item["count"]}
        for item in type_summary_raw
    ]

    agg = bullets.aggregate(
        avg_strength=Avg("strength"),
        max_strength=Max("strength"),
        min_strength=Min("strength"),
        total_helpful=Sum("helpful_count"),
        total_harmful=Sum("harmful_count"),
    )

    return {
        "total_count": bullets.count(),
        "type_summary": type_summary,
        "avg_strength": agg["avg_strength"],
        "max_strength": agg["max_strength"],
        "min_strength": agg["min_strength"],
        "total_helpful": agg["total_helpful"] or 0,
        "total_harmful": agg["total_harmful"] or 0,
    }


def get_analytics_dashboard_context(user):
    metrics = _get_analytics_metrics_for_user(user)
    type_choices = dict(MemoryBullet._meta.get_field("memory_type").choices)
    type_summary = [
        {"label": type_choices.get(d["memory_type"], str(d["memory_type"])), "count": d["count"]}
        for d in metrics["type_distribution_raw"]
    ]

    return {
        "total_memories": metrics["total_memories"],
        "total_sessions": metrics["total_sessions"],
        "total_messages": metrics["total_messages"],
        "avg_strength": metrics["avg_strength"],
        "type_summary": type_summary,
    }


def _apply_chart_style(ax):
    ax.set_facecolor(CHART_BG)
    ax.tick_params(colors=CHART_MUTED, labelsize=9)
    ax.yaxis.grid(True, color=CHART_GRID, linestyle="--", linewidth=0.8, alpha=0.7)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(CHART_GRID)
        ax.spines[spine].set_linewidth(1)


def _render_chart_to_png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def get_memory_type_chart_png(user):
    profile = get_or_create_profile_for_user(user)
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

    fig, ax = plt.subplots(figsize=(7, 5))
    if labels:
        non_zero_count = sum(1 for c in counts if c > 0)
        wedge_linewidth = 0 if non_zero_count <= 1 else 1.2
        wedges, texts, autotexts = ax.pie(
            counts,
            labels=labels,
            autopct="%1.1f%%",
            colors=SEGMENT_COLORS[:len(labels)],
            startangle=140,
            wedgeprops={"linewidth": wedge_linewidth, "edgecolor": "#FFFFFF"},
        )
        for txt in texts:
            txt.set_color(CHART_TEXT)
            txt.set_fontsize(10)
        for txt in autotexts:
            txt.set_color("#FFFFFF")
            txt.set_fontsize(9)
            txt.set_fontweight("semibold")
        ax.set_title("Memory Type Distribution", fontsize=14, fontweight="bold", color=CHART_TEXT, pad=16)
        ax.legend(
            wedges,
            labels,
            title="Memory Type",
            loc="center left",
            bbox_to_anchor=(1.02, 0.5),
            frameon=False,
            labelcolor=CHART_MUTED,
        )
    else:
        ax.text(0.5, 0.5, "No memory data yet", ha="center", va="center", fontsize=14, color=CHART_MUTED)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

    fig.patch.set_facecolor(CHART_BG)
    return _render_chart_to_png(fig)


def get_memory_strength_chart_png(user):
    profile = get_or_create_profile_for_user(user)
    strengths = list(
        MemoryBullet.objects.filter(memory__user=profile).values_list("strength", flat=True)
    )

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
    if strengths:
        bars = ax.bar(
            buckets.keys(),
            buckets.values(),
            color=PROGRESSIVE_COLORS,
            edgecolor="#FFFFFF",
            linewidth=1,
        )
        ax.set_title("Memory Strength Distribution", fontsize=14, fontweight="bold", color=CHART_TEXT, pad=16)
        ax.set_xlabel("Strength Range", color=CHART_MUTED, fontsize=10)
        ax.set_ylabel("Count", color=CHART_MUTED, fontsize=10)
        _apply_chart_style(ax)
        ax.bar_label(bars, padding=3, color=CHART_MUTED, fontsize=9)
        ax.legend(
            [bars[0]],
            ["Memory bullets per strength range"],
            loc="upper right",
            frameon=False,
            labelcolor=CHART_MUTED,
        )
    else:
        ax.text(0.5, 0.5, "No memory data yet", ha="center", va="center", fontsize=14, color=CHART_MUTED)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

    fig.patch.set_facecolor(CHART_BG)
    return _render_chart_to_png(fig)


def get_activity_chart_png(user):
    profile = get_or_create_profile_for_user(user)
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
        x = range(len(days))
        ax.plot(
            x,
            counts,
            marker="o",
            color=PROGRESSIVE_COLORS[0],
            linewidth=2.5,
            markersize=5,
            label="Sessions Created",
        )
        ax.fill_between(x, counts, alpha=0.22, color=PROGRESSIVE_COLORS[-1])
        ax.set_xticks(x)
        ax.set_xticklabels(days, rotation=45, ha="right", fontsize=8, color=CHART_MUTED)
        ax.set_title("Conversation Activity (Last 30 Days)", fontsize=14, fontweight="bold", color=CHART_TEXT, pad=16)
        ax.set_xlabel("Date", color=CHART_MUTED, fontsize=10)
        ax.set_ylabel("Sessions Created", color=CHART_MUTED, fontsize=10)
        _apply_chart_style(ax)
        ax.legend(loc="upper left", frameon=False, labelcolor=CHART_MUTED)
    else:
        ax.text(0.5, 0.5, "No activity data yet", ha="center", va="center", fontsize=14, color=CHART_MUTED)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

    fig.patch.set_facecolor(CHART_BG)
    fig.tight_layout()
    return _render_chart_to_png(fig)


def get_api_memory_bullets_payload(user, q="", memory_type="", topic="", strength_min="", limit=100):
    bullets = _get_memory_bullets_queryset_for_user(user)
    bullets = _apply_memory_bullet_filters(
        bullets,
        q=q,
        memory_type=memory_type,
        topic=topic,
        strength_min=strength_min,
    )

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
        for b in bullets[:limit]
    ]
    return {"count": len(data), "results": data}


def get_api_analytics_summary_payload(user):
    metrics = _get_analytics_metrics_for_user(user)
    return {
        "total_memories": metrics["total_memories"],
        "total_sessions": metrics["total_sessions"],
        "type_distribution": metrics["type_distribution_raw"],
        "avg_strength": metrics["avg_strength"],
        "total_helpful": metrics["total_helpful"],
        "total_harmful": metrics["total_harmful"],
    }


def get_api_sessions_payload(user, q="", limit=50):
    sessions = _get_session_queryset_for_user(user)
    if q:
        sessions = sessions.filter(title__icontains=q.strip())
    data = [
        {
            "id": s.id,
            "title": s.title,
            "created_at": s.created_at.isoformat(),
            "updated_at": s.updated_at.isoformat(),
            "url": s.get_absolute_url(),
        }
        for s in sessions[:limit]
    ]
    return {"count": len(data), "results": data}


def get_api_messages_payload(user, session_id, role_filter=""):
    session = _get_session_or_404_for_user(user, session_id, with_messages=False)

    messages = session.messages.order_by("created_at")
    if role_filter.strip().isdigit():
        messages = messages.filter(role=int(role_filter.strip()))

    data = [
        {
            "id": m.id,
            "role": m.get_role_display(),
            "content": m.content,
            "created_at": m.created_at.isoformat(),
        }
        for m in messages
    ]
    return {"session_id": session_id, "count": len(data), "messages": data}
