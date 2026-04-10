from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.http import require_http_methods

from .holiday_service import (
    HolidayAPIUnavailableError,
    InvalidHolidayCountryCodeError,
    get_daily_activity_with_holidays_payload,
)
from .service import (
    get_api_analytics_summary_payload,
    get_api_daily_active_users_payload,
    get_api_memory_bullets_payload,
    get_api_messages_payload,
    get_api_sessions_payload,
)


@login_required(login_url="/")
@require_http_methods(["GET"])
def api_memory_bullets(request):
    payload = get_api_memory_bullets_payload(
        request.user,
        q=request.GET.get("q", ""),
        memory_type=request.GET.get("type", ""),
        topic=request.GET.get("topic", ""),
        strength_min=request.GET.get("strength_min", ""),
    )
    return JsonResponse(payload)


@login_required(login_url="/")
@require_http_methods(["GET"])
def api_analytics_summary(request):
    return JsonResponse(get_api_analytics_summary_payload(request.user))


@method_decorator(login_required(login_url="/"), name="dispatch")
@method_decorator(require_http_methods(["GET"]), name="dispatch")
class SessionAPIView(View):
    def get(self, request):
        return JsonResponse(
            get_api_sessions_payload(request.user, q=request.GET.get("q", ""))
        )


@method_decorator(login_required(login_url="/"), name="dispatch")
@method_decorator(require_http_methods(["GET"]), name="dispatch")
class MessageAPIView(View):
    def get(self, request, session_id):
        payload = get_api_messages_payload(
            request.user,
            session_id,
            role_filter=request.GET.get("role", ""),
        )
        return JsonResponse(payload)


@require_http_methods(["GET"])
def api_public_daily_active_users(request):
    return JsonResponse(get_api_daily_active_users_payload())


@require_http_methods(["GET"])
def api_public_daily_active_users_with_holidays(request):
    country_param = request.GET.get("country", request.GET.get("q", "US"))
    pretty_json = {"indent": 2}

    try:
        payload = get_daily_activity_with_holidays_payload(
            country_code=country_param,
        )
        return JsonResponse(payload, json_dumps_params=pretty_json)
    except InvalidHolidayCountryCodeError as exc:
        return JsonResponse(
            {
                "error": "invalid_country_code",
                "requested_country_code": exc.country_code,
                "available_regions": exc.available_regions,
            },
            status=400,
            json_dumps_params=pretty_json,
        )
    except HolidayAPIUnavailableError as exc:
        return JsonResponse(
            {
                "error": "holiday_api_unavailable",
                "message": str(exc),
            },
            status=503,
            json_dumps_params=pretty_json,
        )


@login_required(login_url="/")
@require_http_methods(["GET"])
def api_agents(request):
    scope = request.GET.get("scope", "own")
    if scope == "all":
        from .agent_service import get_all_visible_agents
        agents = get_all_visible_agents(request.user)
    else:
        from .agent_service import get_agents_for_user
        agents = get_agents_for_user(request.user, include_inactive=True)
    return JsonResponse({"agents": agents, "count": len(agents)})


@login_required(login_url="/")
@require_http_methods(["GET"])
def api_agent_skills(request, agent_id):
    from .agent_service import get_agent_skills
    enabledOnly = request.GET.get("enabled_only") == "1"
    skills = get_agent_skills(request.user, str(agent_id), enabled_only=enabledOnly)
    return JsonResponse({"skills": skills, "count": len(skills)})


@login_required(login_url="/")
@require_http_methods(["GET"])
def api_notifications(request):
    from .notification_service import get_recent_notifications, get_unread_count
    notifications = get_recent_notifications(request.user, limit=20)
    return JsonResponse({
        "notifications": notifications,
        "unreadCount": get_unread_count(request.user),
    })


@login_required(login_url="/")
@require_http_methods(["GET"])
def api_activity_feed(request):
    from .audit_service import get_activity_feed_for_user
    eventType = (request.GET.get("event_type") or "").strip()
    limit = min(int(request.GET.get("limit", "20") or "20"), 100)
    feed = get_activity_feed_for_user(request.user, limit=limit)
    if eventType:
        feed = [e for e in feed if e.get("eventType") == eventType]
    return JsonResponse({"feed": feed, "count": len(feed)})


@login_required(login_url="/")
@require_http_methods(["GET"])
def api_semantic_search(request):
    query = (request.GET.get("q", "") or "").strip()
    if not query:
        return JsonResponse({"error": "query_required"}, status=400)

    topK = min(int(request.GET.get("top_k", "10") or "10"), 50)

    from app.services import embedding as embeddingService
    if not embeddingService.is_available():
        return JsonResponse({"mode": "unavailable", "results": [], "count": 0})

    from .service import get_or_create_profile_for_user
    from .models import MemoryBullet
    import numpy as np

    profile = get_or_create_profile_for_user(request.user)
    bullets = list(
        MemoryBullet.objects.filter(memory__user=profile)
        .exclude(embedding_json="")
        .values_list("pk", "content", "embedding_json", "memory_type", "topic")
    )

    if not bullets:
        return JsonResponse({"mode": "semantic", "results": [], "count": 0, "indexedCount": 0})

    queryEmbedding = embeddingService.encode_query(query)
    if queryEmbedding is None:
        return JsonResponse({"mode": "fallback", "results": [], "count": 0})

    corpusEmbeddings = []
    validBullets = []
    for pk, content, embJson, memType, topic in bullets:
        vec = embeddingService.json_to_embedding(embJson)
        if vec is not None:
            corpusEmbeddings.append(vec)
            validBullets.append((pk, content, memType, topic))

    if not corpusEmbeddings:
        return JsonResponse({"mode": "semantic", "results": [], "count": 0, "indexedCount": 0})

    corpusMatrix = np.array(corpusEmbeddings)
    ranked = embeddingService.cosine_search(queryEmbedding, corpusMatrix, top_k=topK)

    results = []
    for idx, score in ranked:
        pk, content, memType, topic = validBullets[idx]
        results.append({
            "id": pk,
            "content": content,
            "memoryType": memType,
            "topic": topic or "",
            "similarity": round(score, 4),
        })

    return JsonResponse({
        "mode": "semantic",
        "query": query,
        "results": results,
        "count": len(results),
        "indexedCount": len(validBullets),
    })
