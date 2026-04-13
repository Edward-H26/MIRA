from collections import defaultdict
from datetime import timedelta, datetime

from app.services import neo4j_memory as neo4j
from .service import (
    get_or_create_profile_for_user,
    _get_memory_bullets_for_user,
    MEMORY_TYPE_LABELS,
)


def _get_analytics_metrics_for_user(user):
    profile = get_or_create_profile_for_user(user)
    profileId = str(profile.pk)
    bulletsList = _get_memory_bullets_for_user(user)
    sessions = neo4j.get_sessions_for_user(profileId)
    totalMessages = neo4j.get_total_message_count_for_user(profileId)

    typeCounts = defaultdict(int)
    totalStrength = 0
    totalHelpful = 0
    totalHarmful = 0
    for b in bulletsList:
        typeCounts[b.get("memoryType", 0)] += 1
        totalStrength += b.get("strength", 0) or 0
        totalHelpful += b.get("helpfulCount", 0) or 0
        totalHarmful += b.get("harmfulCount", 0) or 0

    typeDist = [{"memory_type": k, "count": v} for k, v in sorted(typeCounts.items())]
    avgStrength = (totalStrength / len(bulletsList)) if bulletsList else None

    return {
        "total_memories": len(bulletsList),
        "total_sessions": len(sessions),
        "total_messages": totalMessages,
        "avg_strength": avgStrength,
        "total_helpful": totalHelpful,
        "total_harmful": totalHarmful,
        "type_distribution_raw": typeDist,
    }


def _get_performance_metrics(user):
    profile = get_or_create_profile_for_user(user)
    profileId = str(profile.pk)
    logs = neo4j.get_request_logs_for_user(profileId, limit=10000)
    total = len(logs)
    if total == 0:
        return {
            "avg_latency_ms": 0, "p50_latency_ms": 0, "p95_latency_ms": 0,
            "total_requests": 0, "error_rate_pct": 0.0, "throughput_per_day": 0.0,
            "requests_by_status": [],
        }

    latencies = sorted([(lg.get("latencyMs", 0) or 0) for lg in logs])
    n = len(latencies)
    avgLatency = sum(latencies) / n if n else 0
    p50 = (latencies[n // 2 - 1] + latencies[n // 2]) // 2 if n > 1 else (latencies[0] if n == 1 else 0)
    p95Idx = min(int(n * 0.95), n - 1)
    p95 = latencies[p95Idx] if latencies else 0

    errorCount = sum(1 for lg in logs if lg.get("status") == "error")

    timestamps = []
    for lg in logs:
        createdAt = lg.get("createdAt", "")
        if createdAt:
            try:
                if hasattr(createdAt, "isoformat"):
                    timestamps.append(createdAt)
                else:
                    timestamps.append(datetime.fromisoformat(str(createdAt).replace("Z", "+00:00")))
            except Exception:
                pass
    if len(timestamps) >= 2:
        daysActive = max((max(timestamps) - min(timestamps)).days, 1)
    else:
        daysActive = 1

    statusCounts = defaultdict(int)
    for lg in logs:
        statusCounts[lg.get("status", "unknown")] += 1
    statusBreakdown = [{"status": k, "count": v} for k, v in sorted(statusCounts.items())]

    return {
        "avg_latency_ms": round(avgLatency),
        "p50_latency_ms": p50,
        "p95_latency_ms": p95,
        "total_requests": total,
        "error_rate_pct": round((errorCount / total) * 100, 1) if total else 0.0,
        "throughput_per_day": round(total / daysActive, 1),
        "requests_by_status": statusBreakdown,
    }


def _get_cost_metrics(user):
    profile = get_or_create_profile_for_user(user)
    profileId = str(profile.pk)
    logs = neo4j.get_request_logs_for_user(profileId, limit=10000)
    total = len(logs)
    if total == 0:
        return {
            "total_cost_usd": 0.0, "total_tokens": 0, "total_prompt_tokens": 0,
            "total_completion_tokens": 0, "avg_cost_per_request": 0.0, "cost_by_model": [],
        }

    totalCost = sum((lg.get("estimatedCostUsd", 0) or 0) for lg in logs)
    totalPrompt = sum((lg.get("promptTokens", 0) or 0) for lg in logs)
    totalCompletion = sum((lg.get("completionTokens", 0) or 0) for lg in logs)
    totalTok = sum((lg.get("totalTokens", 0) or 0) for lg in logs)

    modelBuckets = defaultdict(lambda: {"total_cost": 0.0, "request_count": 0, "tokens": 0})
    for lg in logs:
        modelName = lg.get("modelName", "unknown")
        modelBuckets[modelName]["total_cost"] += (lg.get("estimatedCostUsd", 0) or 0)
        modelBuckets[modelName]["request_count"] += 1
        modelBuckets[modelName]["tokens"] += (lg.get("totalTokens", 0) or 0)
    costByModel = [
        {"model_name": k, "total_cost": round(v["total_cost"], 6), "request_count": v["request_count"], "tokens": v["tokens"]}
        for k, v in sorted(modelBuckets.items(), key=lambda x: -x[1]["total_cost"])
    ]

    return {
        "total_cost_usd": round(totalCost, 4),
        "total_tokens": totalTok,
        "total_prompt_tokens": totalPrompt,
        "total_completion_tokens": totalCompletion,
        "avg_cost_per_request": round(totalCost / total, 6) if total else 0.0,
        "cost_by_model": costByModel,
    }


def _parse_date_str(dateStr):
    if not dateStr:
        return None
    if hasattr(dateStr, "date"):
        return dateStr
    try:
        return datetime.fromisoformat(str(dateStr).replace("Z", "+00:00"))
    except Exception:
        return None


def get_analytics_dashboard_context(user):
    return get_analytics_dashboard_context_with_reports(user)


def get_analytics_dashboard_context_with_reports(user, session_group="month", memory_group="memory_type"):
    metrics = _get_analytics_metrics_for_user(user)
    profile = get_or_create_profile_for_user(user)
    profileId = str(profile.pk)
    typeSummary = [
        {"label": MEMORY_TYPE_LABELS.get(d["memory_type"], str(d["memory_type"])), "count": d["count"]}
        for d in metrics["type_distribution_raw"]
    ]

    sessionGroup = (session_group or "month").strip().lower()
    if sessionGroup not in {"day", "week", "month"}:
        sessionGroup = "month"

    msgCountsBySession = neo4j.get_message_counts_by_session(profileId)
    sessions = neo4j.get_sessions_for_user(profileId)
    sessionBuckets = defaultdict(lambda: {"session_count": 0, "message_count": 0})
    for s in sessions:
        createdAt = _parse_date_str(s.get("createdAt", ""))
        if not createdAt:
            continue
        if sessionGroup == "day":
            key = createdAt.strftime("%Y-%m-%d") if hasattr(createdAt, "strftime") else str(createdAt)[:10]
        elif sessionGroup == "week":
            dt = createdAt if hasattr(createdAt, "weekday") else createdAt.date() if hasattr(createdAt, "date") else None
            if dt is None:
                continue
            if hasattr(dt, "weekday"):
                weekStart = dt - timedelta(days=dt.weekday())
                key = f"Week of {weekStart.strftime('%Y-%m-%d') if hasattr(weekStart, 'strftime') else str(weekStart)[:10]}"
            else:
                key = str(dt)[:7]
        else:
            key = createdAt.strftime("%Y-%m") if hasattr(createdAt, "strftime") else str(createdAt)[:7]
        sessionBuckets[key]["session_count"] += 1
        sessionId = str(s.get("id", ""))
        sessionBuckets[key]["message_count"] += msgCountsBySession.get(sessionId, {}).get("count", 0)

    sessionGroupedRows = [
        {"group_label": k, "session_count": v["session_count"], "message_count": v["message_count"]}
        for k, v in sorted(sessionBuckets.items(), reverse=True)
    ]

    memoryGroup = (memory_group or "memory_type").strip().lower()
    if memoryGroup not in {"memory_type", "topic", "month"}:
        memoryGroup = "memory_type"

    bulletsList = _get_memory_bullets_for_user(user)
    if memoryGroup == "memory_type":
        buckets = defaultdict(lambda: {"count": 0, "totalStrength": 0})
        for b in bulletsList:
            mt = b.get("memoryType", 0)
            buckets[mt]["count"] += 1
            buckets[mt]["totalStrength"] += b.get("strength", 0) or 0
        memoryGroupedRows = [
            {
                "group_label": MEMORY_TYPE_LABELS.get(k, str(k)),
                "bullet_count": v["count"],
                "avg_strength": (v["totalStrength"] / v["count"]) if v["count"] else None,
            }
            for k, v in sorted(buckets.items())
        ]
    elif memoryGroup == "topic":
        buckets = defaultdict(lambda: {"count": 0, "totalStrength": 0})
        for b in bulletsList:
            topic = b.get("topic", "") or "(No Topic)"
            buckets[topic]["count"] += 1
            buckets[topic]["totalStrength"] += b.get("strength", 0) or 0
        memoryGroupedRows = [
            {
                "group_label": k,
                "bullet_count": v["count"],
                "avg_strength": (v["totalStrength"] / v["count"]) if v["count"] else None,
            }
            for k, v in sorted(buckets.items())
        ]
    else:
        buckets = defaultdict(lambda: {"count": 0, "totalStrength": 0})
        for b in bulletsList:
            createdAt = _parse_date_str(b.get("createdAt", ""))
            if not createdAt:
                continue
            key = createdAt.strftime("%Y-%m") if hasattr(createdAt, "strftime") else str(createdAt)[:7]
            buckets[key]["count"] += 1
            buckets[key]["totalStrength"] += b.get("strength", 0) or 0
        memoryGroupedRows = [
            {
                "group_label": k,
                "bullet_count": v["count"],
                "avg_strength": (v["totalStrength"] / v["count"]) if v["count"] else None,
            }
            for k, v in sorted(buckets.items(), reverse=True)
        ]

    context = {
        "total_memories": metrics["total_memories"],
        "total_sessions": metrics["total_sessions"],
        "total_messages": metrics["total_messages"],
        "avg_strength": metrics["avg_strength"],
        "type_summary": typeSummary,
        "session_group": sessionGroup,
        "memory_group": memoryGroup,
        "session_grouped_rows": sessionGroupedRows,
        "memory_grouped_rows": memoryGroupedRows,
        "session_group_count": len(sessionGroupedRows),
        "memory_group_count": len(memoryGroupedRows),
    }

    perf = _get_performance_metrics(user)
    context["perf_avg_latency"] = perf["avg_latency_ms"]
    context["perf_p50_latency"] = perf["p50_latency_ms"]
    context["perf_p95_latency"] = perf["p95_latency_ms"]
    context["perf_total_requests"] = perf["total_requests"]
    context["perf_error_rate"] = perf["error_rate_pct"]
    context["perf_throughput"] = perf["throughput_per_day"]
    context["perf_requests_by_status"] = perf["requests_by_status"]

    cost = _get_cost_metrics(user)
    context["cost_total"] = cost["total_cost_usd"]
    context["cost_total_tokens"] = cost["total_tokens"]
    context["cost_prompt_tokens"] = cost["total_prompt_tokens"]
    context["cost_completion_tokens"] = cost["total_completion_tokens"]
    context["cost_avg_per_request"] = cost["avg_cost_per_request"]
    context["cost_by_model"] = cost["cost_by_model"]

    return context


def get_session_report_export_rows(user, q=""):
    profile = get_or_create_profile_for_user(user)
    profileId = str(profile.pk)
    normalizedQ = (q or "").strip().lower()
    sessions = neo4j.get_sessions_for_user(profileId)
    if normalizedQ:
        sessions = [s for s in sessions if normalizedQ in (s.get("title", "") or "").lower()]

    rows = []
    for s in sessions:
        sessionId = str(s.get("id", ""))
        msgs = neo4j.get_messages_for_session(sessionId)
        createdAt = s.get("createdAt", "")
        if hasattr(createdAt, "isoformat"):
            createdAt = createdAt.isoformat()
        rows.append({
            "title": s.get("title", ""),
            "created_at": str(createdAt),
            "message_count": len(msgs),
        })
    return rows


def get_memory_bullet_report_export_rows(user, q=""):
    bulletsList = _get_memory_bullets_for_user(user)
    normalizedQ = (q or "").strip().lower()
    if normalizedQ:
        bulletsList = [b for b in bulletsList if normalizedQ in (b.get("content", "") or "").lower()]

    rows = []
    for b in bulletsList:
        createdAt = b.get("createdAt", "")
        if hasattr(createdAt, "isoformat"):
            createdAt = createdAt.isoformat()
        rows.append({
            "content": b.get("content", ""),
            "memory_type": MEMORY_TYPE_LABELS.get(b.get("memoryType", 0), str(b.get("memoryType", ""))),
            "created_at": str(createdAt),
        })
    return rows


def get_request_log_export_rows(user):
    profile = get_or_create_profile_for_user(user)
    profileId = str(profile.pk)
    logs = neo4j.get_request_logs_for_user(profileId, limit=500)
    rows = []
    for lg in logs:
        createdAt = lg.get("createdAt", "")
        if hasattr(createdAt, "isoformat"):
            createdAt = createdAt.isoformat()
        rows.append({
            "request_type": lg.get("requestType", ""),
            "model_name": lg.get("modelName", ""),
            "status": lg.get("status", ""),
            "latency_ms": lg.get("latencyMs", 0),
            "total_tokens": lg.get("totalTokens", 0),
            "estimated_cost_usd": round(lg.get("estimatedCostUsd", 0) or 0, 6),
            "created_at": str(createdAt),
        })
    return rows


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


def get_api_daily_active_users_payload():
    return {"count": 0, "results": []}
