import io
import math
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from django.utils import timezone

from app.services import neo4j_memory as neo4j
from .service import (
    get_or_create_profile_for_user,
    _get_memory_bullets_for_user,
    PROGRESSIVE_COLORS,
    SEGMENT_COLORS,
    CHART_BG,
    CHART_GRID,
    CHART_TEXT,
    CHART_MUTED,
    MEMORY_TYPE_LABELS,
)
from .analytics_service import _parse_date_str


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
    bulletsList = _get_memory_bullets_for_user(user)
    typeCounts = defaultdict(int)
    for b in bulletsList:
        typeCounts[b.get("memoryType", 0)] += 1
    typeData = sorted(typeCounts.items())
    labels = [MEMORY_TYPE_LABELS.get(k, str(k)) for k, v in typeData]
    counts = [v for k, v in typeData]

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
    bulletsList = _get_memory_bullets_for_user(user)
    strengths = [(b.get("strength", 0) or 0) for b in bulletsList]

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
            list(buckets.keys()),
            list(buckets.values()),
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
    profileId = str(profile.pk)
    sessions = neo4j.get_sessions_for_user(profileId)
    thirtyDaysAgo = timezone.now() - timezone.timedelta(days=30)

    dailyCounts = defaultdict(int)
    for s in sessions:
        createdAt = _parse_date_str(s.get("createdAt", ""))
        if not createdAt:
            continue
        if hasattr(thirtyDaysAgo, "tzinfo") and hasattr(createdAt, "date"):
            try:
                if createdAt < thirtyDaysAgo:
                    continue
            except TypeError:
                pass
        dt = createdAt.date() if hasattr(createdAt, "date") else createdAt
        dailyCounts[dt] += 1

    daily = sorted(dailyCounts.items())

    fig, ax = plt.subplots(figsize=(8, 4))
    if daily:
        days = [d[0].strftime("%m/%d") if hasattr(d[0], "strftime") else str(d[0]) for d in daily]
        counts = [d[1] for d in daily]
        x = range(len(days))
        ax.plot(x, counts, marker="o", color=PROGRESSIVE_COLORS[0], linewidth=2.5, markersize=5, label="Sessions Created")
        ax.fill_between(x, counts, alpha=0.22, color=PROGRESSIVE_COLORS[-1])
        ax.set_xticks(x)
        ax.set_xticklabels(days, rotation=45, ha="right", fontsize=8, color=CHART_MUTED)
        ax.set_title("Conversation Activity (Last 30 Days)", fontsize=14, fontweight="bold", color=CHART_TEXT, pad=16)
        ax.set_xlabel("Date", color=CHART_MUTED, fontsize=10)
        ax.set_ylabel("Sessions Created", color=CHART_MUTED, fontsize=10)
        max_count = max(counts)
        ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
        ax.set_ylim(bottom=0, top=max_count + max(1, math.ceil(max_count * 0.15)))
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


def get_latency_over_time_chart_png(user):
    profile = get_or_create_profile_for_user(user)
    profileId = str(profile.pk)
    logs = neo4j.get_request_logs_by_date(profileId, days=30)

    dailyLatencies = defaultdict(list)
    for lg in logs:
        createdAt = _parse_date_str(lg.get("createdAt", ""))
        if not createdAt:
            continue
        dt = createdAt.date() if hasattr(createdAt, "date") else createdAt
        dailyLatencies[dt].append(lg.get("latencyMs", 0) or 0)

    daily = sorted(dailyLatencies.items())

    fig, ax = plt.subplots(figsize=(8, 4))
    if daily:
        days = [d[0].strftime("%m/%d") if hasattr(d[0], "strftime") else str(d[0]) for d in daily]
        latencies = [float(sum(d[1]) / len(d[1])) if d[1] else 0 for d in daily]
        x = range(len(days))
        ax.plot(x, latencies, marker="o", color=PROGRESSIVE_COLORS[0], linewidth=2.5, markersize=5, label="Avg Latency (ms)")
        ax.fill_between(x, latencies, alpha=0.22, color=PROGRESSIVE_COLORS[-1])
        ax.set_xticks(x)
        ax.set_xticklabels(days, rotation=45, ha="right", fontsize=8, color=CHART_MUTED)
        ax.set_title("Average Latency (Last 30 Days)", fontsize=14, fontweight="bold", color=CHART_TEXT, pad=16)
        ax.set_xlabel("Date", color=CHART_MUTED, fontsize=10)
        ax.set_ylabel("Latency (ms)", color=CHART_MUTED, fontsize=10)
        _apply_chart_style(ax)
        ax.legend(loc="upper left", frameon=False, labelcolor=CHART_MUTED)
    else:
        ax.text(0.5, 0.5, "No data yet", ha="center", va="center", fontsize=14, color=CHART_MUTED)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

    fig.patch.set_facecolor(CHART_BG)
    fig.tight_layout()
    return _render_chart_to_png(fig)


def get_latency_by_model_chart_png(user):
    profile = get_or_create_profile_for_user(user)
    profileId = str(profile.pk)
    logs = neo4j.get_request_logs_for_user(profileId, limit=10000)

    modelLatencies = defaultdict(list)
    for lg in logs:
        modelLatencies[lg.get("modelName", "unknown")].append(lg.get("latencyMs", 0) or 0)
    modelData = sorted(modelLatencies.items())

    fig, ax = plt.subplots(figsize=(7, 5))
    if modelData:
        models = [d[0] for d in modelData]
        latencies = [float(sum(d[1]) / len(d[1])) if d[1] else 0 for d in modelData]
        colors = PROGRESSIVE_COLORS[:len(models)]
        bars = ax.barh(models, latencies, color=colors, edgecolor="#FFFFFF", linewidth=1)
        ax.set_title("Average Latency by Model", fontsize=14, fontweight="bold", color=CHART_TEXT, pad=16)
        ax.set_xlabel("Latency (ms)", color=CHART_MUTED, fontsize=10)
        _apply_chart_style(ax)
        ax.bar_label(bars, fmt="%.0f", padding=3, color=CHART_MUTED, fontsize=9)
    else:
        ax.text(0.5, 0.5, "No data yet", ha="center", va="center", fontsize=14, color=CHART_MUTED)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

    fig.patch.set_facecolor(CHART_BG)
    fig.tight_layout()
    return _render_chart_to_png(fig)


def get_error_rate_chart_png(user):
    profile = get_or_create_profile_for_user(user)
    profileId = str(profile.pk)
    logs = neo4j.get_request_logs_for_user(profileId, limit=10000)

    statusCounts = defaultdict(int)
    for lg in logs:
        statusCounts[lg.get("status", "unknown")] += 1
    statusData = sorted(statusCounts.items())

    fig, ax = plt.subplots(figsize=(7, 5))
    if statusData:
        labels = [d[0] for d in statusData]
        counts = [d[1] for d in statusData]
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
        ax.set_title("Request Status Distribution", fontsize=14, fontweight="bold", color=CHART_TEXT, pad=16)
        ax.legend(
            wedges, labels, title="Status", loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False, labelcolor=CHART_MUTED,
        )
    else:
        ax.text(0.5, 0.5, "No data yet", ha="center", va="center", fontsize=14, color=CHART_MUTED)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

    fig.patch.set_facecolor(CHART_BG)
    return _render_chart_to_png(fig)


def get_daily_cost_chart_png(user):
    profile = get_or_create_profile_for_user(user)
    profileId = str(profile.pk)
    logs = neo4j.get_request_logs_by_date(profileId, days=30)

    dailyCosts = defaultdict(float)
    for lg in logs:
        createdAt = _parse_date_str(lg.get("createdAt", ""))
        if not createdAt:
            continue
        dt = createdAt.date() if hasattr(createdAt, "date") else createdAt
        dailyCosts[dt] += float(lg.get("estimatedCostUsd", 0) or 0)

    daily = sorted(dailyCosts.items())

    fig, ax = plt.subplots(figsize=(8, 4))
    if daily:
        days = [d[0].strftime("%m/%d") if hasattr(d[0], "strftime") else str(d[0]) for d in daily]
        costs = [d[1] for d in daily]
        x = range(len(days))
        ax.plot(x, costs, marker="o", color=PROGRESSIVE_COLORS[0], linewidth=2.5, markersize=5, label="Daily Cost (USD)")
        ax.fill_between(x, costs, alpha=0.22, color=PROGRESSIVE_COLORS[-1])
        ax.set_xticks(x)
        ax.set_xticklabels(days, rotation=45, ha="right", fontsize=8, color=CHART_MUTED)
        ax.set_title("Daily Cost (Last 30 Days)", fontsize=14, fontweight="bold", color=CHART_TEXT, pad=16)
        ax.set_xlabel("Date", color=CHART_MUTED, fontsize=10)
        ax.set_ylabel("Cost (USD)", color=CHART_MUTED, fontsize=10)
        _apply_chart_style(ax)
        ax.legend(loc="upper left", frameon=False, labelcolor=CHART_MUTED)
    else:
        ax.text(0.5, 0.5, "No data yet", ha="center", va="center", fontsize=14, color=CHART_MUTED)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

    fig.patch.set_facecolor(CHART_BG)
    fig.tight_layout()
    return _render_chart_to_png(fig)


def get_token_usage_chart_png(user):
    profile = get_or_create_profile_for_user(user)
    profileId = str(profile.pk)
    logs = neo4j.get_request_logs_by_date(profileId, days=30)

    dailyPrompt = defaultdict(int)
    dailyCompletion = defaultdict(int)
    for lg in logs:
        createdAt = _parse_date_str(lg.get("createdAt", ""))
        if not createdAt:
            continue
        dt = createdAt.date() if hasattr(createdAt, "date") else createdAt
        dailyPrompt[dt] += lg.get("promptTokens", 0) or 0
        dailyCompletion[dt] += lg.get("completionTokens", 0) or 0

    allDays = sorted(set(dailyPrompt.keys()) | set(dailyCompletion.keys()))

    fig, ax = plt.subplots(figsize=(8, 4))
    if allDays:
        days = [d.strftime("%m/%d") if hasattr(d, "strftime") else str(d) for d in allDays]
        prompt_vals = [dailyPrompt.get(d, 0) for d in allDays]
        completion_vals = [dailyCompletion.get(d, 0) for d in allDays]
        x = range(len(days))
        ax.bar(x, prompt_vals, color=PROGRESSIVE_COLORS[0], label="Prompt Tokens", edgecolor="#FFFFFF", linewidth=1)
        ax.bar(x, completion_vals, bottom=prompt_vals, color=PROGRESSIVE_COLORS[2], label="Completion Tokens", edgecolor="#FFFFFF", linewidth=1)
        ax.set_xticks(list(x))
        ax.set_xticklabels(days, rotation=45, ha="right", fontsize=8, color=CHART_MUTED)
        ax.set_title("Token Usage (Last 30 Days)", fontsize=14, fontweight="bold", color=CHART_TEXT, pad=16)
        ax.set_xlabel("Date", color=CHART_MUTED, fontsize=10)
        ax.set_ylabel("Tokens", color=CHART_MUTED, fontsize=10)
        _apply_chart_style(ax)
        ax.legend(loc="upper left", frameon=False, labelcolor=CHART_MUTED)
    else:
        ax.text(0.5, 0.5, "No data yet", ha="center", va="center", fontsize=14, color=CHART_MUTED)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

    fig.patch.set_facecolor(CHART_BG)
    fig.tight_layout()
    return _render_chart_to_png(fig)


def get_cost_by_model_chart_png(user):
    profile = get_or_create_profile_for_user(user)
    profileId = str(profile.pk)
    logs = neo4j.get_request_logs_for_user(profileId, limit=10000)

    modelCosts = defaultdict(float)
    for lg in logs:
        modelCosts[lg.get("modelName", "unknown")] += float(lg.get("estimatedCostUsd", 0) or 0)
    modelData = sorted(modelCosts.items(), key=lambda x: -x[1])

    fig, ax = plt.subplots(figsize=(7, 5))
    if modelData:
        models = [d[0] for d in modelData]
        costs = [d[1] for d in modelData]
        colors = PROGRESSIVE_COLORS[:len(models)]
        bars = ax.bar(models, costs, color=colors, edgecolor="#FFFFFF", linewidth=1)
        ax.set_title("Total Cost by Model", fontsize=14, fontweight="bold", color=CHART_TEXT, pad=16)
        ax.set_xlabel("Model", color=CHART_MUTED, fontsize=10)
        ax.set_ylabel("Cost (USD)", color=CHART_MUTED, fontsize=10)
        _apply_chart_style(ax)
        ax.bar_label(bars, fmt="$%.4f", padding=3, color=CHART_MUTED, fontsize=9)
    else:
        ax.text(0.5, 0.5, "No data yet", ha="center", va="center", fontsize=14, color=CHART_MUTED)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

    fig.patch.set_facecolor(CHART_BG)
    fig.tight_layout()
    return _render_chart_to_png(fig)
