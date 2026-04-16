import asyncio
import csv
import json
import time

from asgiref.sync import sync_to_async
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from app.services import neo4j_memory as neo4j
from memoria.event_log import log_event
from .service import (
    stream_user_message_with_agent_reply,
    start_background_generation,
    subscribe_to_active_generation,
    subscribe_to_active_generation_async,
    stream_queue_payloads,
    get_or_create_profile_for_user,
    get_memory_list_data,
    get_memory_summary,
    get_session_for_user,
    get_session_for_user_or_member,
    get_sidebar_sessions_for_user,
)
from .analytics_service import (
    get_analytics_dashboard_context_with_reports,
    get_memory_bullet_report_export_rows,
    get_session_report_export_rows,
    get_request_log_export_rows,
)
from .chart_service import (
    get_memory_strength_chart_png,
    get_memory_type_chart_png,
    get_activity_chart_png,
    get_latency_over_time_chart_png,
    get_latency_by_model_chart_png,
    get_error_rate_chart_png,
    get_daily_cost_chart_png,
    get_token_usage_chart_png,
    get_cost_by_model_chart_png,
)

PENDING_PROMPT_SESSION_KEY = "pending_chat_prompts"


@login_required(login_url="/")
def memory_list_view(request):
    searchQuery = (request.POST.get("q") or request.GET.get("q") or "").strip()
    memoryType = (request.POST.get("type") or request.GET.get("type") or "").strip()
    sortKey = (request.POST.get("sort") or request.GET.get("sort") or "created").strip()
    payload = get_memory_list_data(
        request.user,
        search_query=searchQuery,
        memory_type=memoryType,
        sort_key=sortKey,
    )
    profile = get_or_create_profile_for_user(request.user)
    bullets = payload["queryset"]
    bulletIds = [b.get("id", "") for b in bullets if b.get("id")]
    userVotes = neo4j.get_user_votes_batch(str(profile.pk), bulletIds)
    context = {
        "bullets": bullets,
        "memory_type_choices": payload["memory_type_choices"],
        "active_memory_type": payload["active_memory_type"],
        "search_query": payload["search_query"],
        "sort_label": payload["sort_label"],
        "active_sort": payload["active_sort"],
        "user_votes": userVotes,
    }
    context.update(get_memory_summary(request.user))
    return render(request, "chat/memory.html", context)


@login_required(login_url="/")
async def conversation_messages_view(request, session_id):
    if request.method == "GET":
        return await sync_to_async(_conversation_messages_get, thread_sensitive=True)(request, session_id)
    return await _conversation_messages_post(request, session_id)


def _conversation_messages_get(request, session_id):
    try:
        session = get_session_for_user(request.user, session_id, with_messages=True)
    except Http404:
        profile = get_or_create_profile_for_user(request.user)
        members = neo4j.get_members_for_session(str(session_id))
        isMember = any(str(m.get("userId", "")) == str(profile.pk) for m in members)
        if not isMember:
            raise Http404
        session = neo4j.get_session_by_id(str(session_id))
        if session is None:
            raise Http404
        session["messages"] = neo4j.get_messages_for_session(str(session_id))
    # Populate live member info + count. Without this the info panel's
    # "Members ()" template tag renders empty and the auto-refreshed count
    # in the header pill shows nothing.
    try:
        if session.get("accessKey"):
            membersList = neo4j.get_members_for_session(str(session["id"]))
            session["members"] = membersList
            session["memberCount"] = len(membersList)
    except Exception:
        pass
    try:
        from .notification_service import mark_read_by_related_url
        mark_read_by_related_url(request.user, f"/chat/c/{session['id']}/")
    except Exception:
        pass
    isGenerating = neo4j.ensure_generation_lock_fresh(session["id"])
    pendingPrompts = dict(request.session.get(PENDING_PROMPT_SESSION_KEY, {}))
    pendingPrompt = pendingPrompts.pop(str(session["id"]), "")
    if pendingPrompts:
        request.session[PENDING_PROMPT_SESSION_KEY] = pendingPrompts
    else:
        request.session.pop(PENDING_PROMPT_SESSION_KEY, None)
    if pendingPrompt:
        request.session.modified = True
    return render(
        request,
        "chat/conversation_detail.html",
        {
            "session": session,
            "pending_prompt": pendingPrompt,
            "generation_in_progress": isGenerating,
        },
    )


async def _conversation_messages_post(request, session_id):
    try:
        user = request.user
        session = await sync_to_async(get_session_for_user, thread_sensitive=True)(user, session_id)
        profile = await sync_to_async(get_or_create_profile_for_user, thread_sensitive=True)(user)
    except Http404:
        raise
    except Exception as exc:
        log_event("chat_message_submit_setup_failed", request=request, session_id=str(session_id), error=str(exc))
        return JsonResponse({"error": "service_busy", "message": "Please retry in a moment."}, status=503)

    session["_user"] = user
    session["_profile_id"] = str(profile.pk)
    content = (request.POST.get("message") or "").strip()
    if not content:
        return JsonResponse({"error": "Empty message"}, status=400)
    sessionId = session["id"]
    log_event("chat_message_submit", request=request, session_id=sessionId)

    try:
        acquired = await sync_to_async(neo4j.acquire_session_generation_lock)(sessionId)
    except Exception as exc:
        log_event("chat_message_submit_lock_failed", request=request, session_id=sessionId, error=str(exc))
        return JsonResponse({"error": "service_busy"}, status=503)

    if not acquired:
        log_event("chat_generation_rejected_locked", request=request, session_id=sessionId)
        return JsonResponse(
            {"error": "generation_in_progress", "message": "Previous response is still generating."},
            status=409,
        )

    autoTitle = None
    try:
        from .write_service import update_session_with_outbox
        has_messages = await sync_to_async(neo4j.session_has_messages)(sessionId)
        if session.get("title", "") in ("New Chat", "") and not has_messages:
            autoTitle = content[:60].strip()
            if autoTitle:
                await sync_to_async(update_session_with_outbox)(sessionId, title=autoTitle)
    except Exception as exc:
        log_event("chat_message_submit_title_failed", request=request, session_id=sessionId, error=str(exc))

    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        def _run_sync():
            try:
                for _ in stream_user_message_with_agent_reply(session, content):
                    pass
            finally:
                neo4j.release_session_generation_lock(sessionId)
        await sync_to_async(_run_sync)()
        return redirect(f"/chat/c/{sessionId}/")

    try:
        queue = await sync_to_async(start_background_generation, thread_sensitive=True)(session, content)
    except TimeoutError:
        await sync_to_async(neo4j.release_session_generation_lock)(sessionId)
        return JsonResponse(
            {"error": "service_busy", "message": "The agent service is at capacity; please retry in a moment."},
            status=503,
        )
    except Exception as exc:
        log_event("chat_background_start_failed", request=request, session_id=sessionId, error=str(exc))
        await sync_to_async(neo4j.release_session_generation_lock)(sessionId)
        return JsonResponse(
            {"error": "service_busy", "message": "The agent service could not start; please retry."},
            status=503,
        )

    def event_stream():
        titleInjected = not autoTitle
        for payload in stream_queue_payloads(queue):
            if not titleInjected:
                payload = {**payload, "auto_title": autoTitle, "session_id": sessionId}
                titleInjected = True
            yield (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")

    response = StreamingHttpResponse(
        event_stream(),
        content_type="application/x-ndjson; charset=utf-8",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required(login_url="/")
@require_http_methods(["POST"])
def message_edit_view(request, session_id, message_id):
    get_session_for_user(request.user, session_id)
    content = (request.POST.get("content") or "").strip()
    if not content:
        return JsonResponse({"error": "Content required"}, status=400)
    updated = neo4j.edit_message(str(message_id), content)
    if updated is None:
        return JsonResponse({"error": "Message not found"}, status=404)
    return JsonResponse({"ok": True, "content": updated.get("content", content)})


@login_required(login_url="/")
@require_http_methods(["POST"])
async def message_resend_view(request, session_id, message_id):
    user = request.user
    session = await sync_to_async(get_session_for_user, thread_sensitive=True)(user, session_id)
    profile = await sync_to_async(get_or_create_profile_for_user, thread_sensitive=True)(user)
    session["_user"] = user
    session["_profile_id"] = str(profile.pk)
    sessionId = session["id"]

    allMessages = await sync_to_async(neo4j.get_messages_for_session)(sessionId)
    targetMsg = None
    for m in allMessages:
        if str(m.get("id", "")) == str(message_id) and m.get("role") == "user":
            targetMsg = m
            break
    if targetMsg is None:
        return JsonResponse({"error": "Message not found"}, status=404)

    acquired = await sync_to_async(neo4j.acquire_session_generation_lock)(sessionId)
    if not acquired:
        return JsonResponse({"error": "generation_in_progress"}, status=409)

    def _prune_later_messages():
        targetCreatedAt = targetMsg.get("createdAt", "")
        for m in allMessages:
            if m.get("createdAt", "") > targetCreatedAt:
                neo4j.delete_message(str(m["id"]))
    await sync_to_async(_prune_later_messages)()

    try:
        queue = await sync_to_async(start_background_generation, thread_sensitive=True)(
            session, targetMsg.get("content", ""), skip_user_message=True,
        )
    except TimeoutError:
        await sync_to_async(neo4j.release_session_generation_lock)(sessionId)
        return JsonResponse({"error": "service_busy"}, status=503)

    def event_stream():
        for payload in stream_queue_payloads(queue):
            yield (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")

    response = StreamingHttpResponse(
        event_stream(),
        content_type="application/x-ndjson; charset=utf-8",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required(login_url="/")
@require_http_methods(["POST"])
async def conversation_upload_view(request, session_id):
    user = request.user
    session = await sync_to_async(get_session_for_user, thread_sensitive=True)(user, session_id)
    sessionId = session["id"]

    uploadedFile = request.FILES.get("file")
    if not uploadedFile:
        return JsonResponse({"error": "No file uploaded"}, status=400)

    from app.services.ocr import validate_uploaded_image, extract_text_from_file

    isValid, errorMsg = validate_uploaded_image(uploadedFile)
    if not isValid:
        return JsonResponse({"error": errorMsg}, status=400)

    try:
        ocrResult = await sync_to_async(extract_text_from_file)(uploadedFile)
    except Exception as exc:
        log_event("chat_upload_ocr_crash", session_id=sessionId, error=str(exc))
        return JsonResponse({"error": f"Document processing failed: {exc}"}, status=400)

    if ocrResult.status != "success":
        return JsonResponse({"error": ocrResult.error or "OCR extraction failed"}, status=400)

    userMessage = (request.POST.get("message") or "").strip()
    truncatedText = ocrResult.raw_text[:500]

    displayContent = userMessage or "Analyze this document"
    displayContent += f"\n[Attached: {uploadedFile.name}]"

    aiPromptParts = []
    if userMessage:
        aiPromptParts.append(userMessage)
    aiPromptParts.append(
        f"[Uploaded document: {uploadedFile.name}]\n\n"
        f"Extracted text:\n{truncatedText}"
    )
    aiPrompt = "\n\n".join(aiPromptParts)

    log_event("chat_document_upload", request=request, session_id=sessionId)

    acquired = await sync_to_async(neo4j.acquire_session_generation_lock)(sessionId)
    if not acquired:
        return JsonResponse({"error": "generation_in_progress"}, status=409)

    profile = await sync_to_async(get_or_create_profile_for_user, thread_sensitive=True)(user)
    await sync_to_async(neo4j.create_message)(
        sessionId, displayContent, str(profile.pk), role="user",
    )

    try:
        queue = await sync_to_async(start_background_generation, thread_sensitive=True)(
            session, aiPrompt, skip_user_message=True,
        )
    except TimeoutError:
        await sync_to_async(neo4j.release_session_generation_lock)(sessionId)
        return JsonResponse({"error": "service_busy"}, status=503)

    def event_stream():
        for payload in stream_queue_payloads(queue):
            yield (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")

    response = StreamingHttpResponse(
        event_stream(),
        content_type="application/x-ndjson; charset=utf-8",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required(login_url="/")
def memory_bullets_view(request, memory_id):
    profile = get_or_create_profile_for_user(request.user)
    memory = neo4j.get_memory(str(memory_id))
    if memory is not None:
        bullets = neo4j.get_bullets_for_memory(str(memory_id), learner_id=str(profile.pk))
        memory["bullets"] = bullets
        return render(request, "chat/memory_detail.html", {"memory": memory})
    bullet = neo4j.get_bullet(str(memory_id))
    if bullet is None:
        raise Http404
    memory = {"id": memory_id, "bullets": [bullet], "access_clock": "", "created_at": "", "updated_at": ""}
    return render(request, "chat/memory_detail.html", {"memory": memory})


@login_required(login_url="/")
@require_http_methods(["GET"])
def conversation_lock_status_view(request, session_id):
    session = get_session_for_user(request.user, session_id)
    sessionId = session["id"]
    isGenerating = neo4j.ensure_generation_lock_fresh(sessionId)
    return JsonResponse(
        {
            "session_id": sessionId,
            "generation_in_progress": isGenerating,
            "generation_started_at": session.get("generationStartedAt"),
            "updated_at": session.get("updatedAt", ""),
        }
    )


@login_required(login_url="/")
@require_http_methods(["GET"])
async def conversation_stream_subscribe_view(request, session_id):
    """Subscribe to an in-flight agent generation.

    When a user navigates back to a conversation whose agent is still thinking,
    the browser calls this endpoint to reconnect to the live stream. The
    subscriber queue is seeded with any payloads already produced, then
    forwards new payloads as the background worker emits them. If no generation
    is active, the response ends immediately so the client can fall back to
    polling the lock endpoint.
    """
    session = await sync_to_async(get_session_for_user, thread_sensitive=True)(request.user, session_id)
    sessionId = session["id"]
    queue = await sync_to_async(subscribe_to_active_generation, thread_sensitive=True)(sessionId)

    def event_stream():
        if queue is None:
            return
        for payload in stream_queue_payloads(queue):
            yield (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")

    response = StreamingHttpResponse(
        event_stream(),
        content_type="application/x-ndjson; charset=utf-8",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required(login_url="/")
@require_http_methods(["GET"])
async def conversation_wait_for_unlock_view(request, session_id):
    """Block until the session generation lock is released, or until the client's
    timeout budget expires. Under ASGI this coroutine sleeps on
    ``asyncio.wait_for(queue.get, ...)`` — the worker thread is released for
    other requests while this coroutine is parked on the event loop."""
    session = await sync_to_async(get_session_for_user, thread_sensitive=True)(request.user, session_id)
    sessionId = session["id"]
    try:
        timeoutSeconds = int(request.GET.get("timeout", "55"))
    except (TypeError, ValueError):
        timeoutSeconds = 55
    timeoutSeconds = min(max(timeoutSeconds, 5), 120)

    def _ok_released():
        return JsonResponse({
            "session_id": sessionId,
            "generation_in_progress": False,
            "timed_out": False,
        })

    def _ok_timed_out():
        return JsonResponse({
            "session_id": sessionId,
            "generation_in_progress": True,
            "timed_out": True,
        })

    is_fresh = await sync_to_async(neo4j.ensure_generation_lock_fresh)(sessionId)
    if not is_fresh:
        return _ok_released()

    queue = subscribe_to_active_generation_async(sessionId)
    deadline = time.monotonic() + timeoutSeconds

    if queue is not None:
        while time.monotonic() < deadline:
            remaining = max(0.5, min(5.0, deadline - time.monotonic()))
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                continue
            if payload is None:
                return _ok_released()
        return _ok_timed_out()

    # Fallback: no local broadcast (orphan lock from previous process or
    # different worker). Poll the DB infrequently without blocking the worker.
    while time.monotonic() < deadline:
        await asyncio.sleep(2)
        still_fresh = await sync_to_async(neo4j.ensure_generation_lock_fresh)(sessionId)
        if not still_fresh:
            return _ok_released()
    return _ok_timed_out()


@login_required(login_url="/")
@require_http_methods(["POST"])
def session_rename_view(request, session_id):
    from .write_service import update_session_with_outbox
    session = get_session_for_user_or_member(request.user, session_id, require_admin=True)
    title = (request.POST.get("title") or "").strip()
    if not title:
        return JsonResponse({"error": "Title is required"}, status=400)
    trimmedTitle = title[:200]
    update_session_with_outbox(session["id"], title=trimmedTitle)
    log_event("chat_session_updated", request=request, session_id=session["id"], action="rename")
    return JsonResponse({"ok": True, "title": trimmedTitle})


@login_required(login_url="/")
@require_http_methods(["POST"])
def session_delete_view(request, session_id):
    from .write_service import delete_session_with_outbox
    session = get_session_for_user(request.user, session_id)
    deletedId = session["id"]
    delete_session_with_outbox(deletedId)
    log_event("chat_session_updated", request=request, session_id=deletedId, action="delete")
    return JsonResponse({"ok": True})


@login_required(login_url="/")
def analytics_view(request):
    context = get_analytics_dashboard_context_with_reports(
        request.user,
        session_group=request.GET.get("session_group", "month"),
        memory_group=request.GET.get("memory_group", "memory_type"),
    )
    return render(request, "chat/analytics.html", context)


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


@login_required(login_url="/")
@require_http_methods(["GET"])
def latency_over_time_chart_png(request):
    return HttpResponse(get_latency_over_time_chart_png(request.user), content_type="image/png")


@login_required(login_url="/")
@require_http_methods(["GET"])
def latency_by_model_chart_png(request):
    return HttpResponse(get_latency_by_model_chart_png(request.user), content_type="image/png")


@login_required(login_url="/")
@require_http_methods(["GET"])
def error_rate_chart_png(request):
    return HttpResponse(get_error_rate_chart_png(request.user), content_type="image/png")


@login_required(login_url="/")
@require_http_methods(["GET"])
def daily_cost_chart_png(request):
    return HttpResponse(get_daily_cost_chart_png(request.user), content_type="image/png")


@login_required(login_url="/")
@require_http_methods(["GET"])
def token_usage_chart_png(request):
    return HttpResponse(get_token_usage_chart_png(request.user), content_type="image/png")


@login_required(login_url="/")
@require_http_methods(["GET"])
def cost_by_model_chart_png(request):
    return HttpResponse(get_cost_by_model_chart_png(request.user), content_type="image/png")


@login_required(login_url="/")
@require_http_methods(["GET"])
def export_request_log_report(request):
    export_format = (request.GET.get("format", "csv") or "csv").strip().lower()
    rows = get_request_log_export_rows(request.user)
    return _export_rows_response(
        rows=rows,
        export_format=export_format,
        filename_prefix="request_log",
        csv_headers=["request_type", "model_name", "status", "latency_ms", "total_tokens", "estimated_cost_usd", "created_at"],
        csv_field_order=["request_type", "model_name", "status", "latency_ms", "total_tokens", "estimated_cost_usd", "created_at"],
        json_key="request_logs",
    )


@login_required(login_url="/")
@require_http_methods(["GET"])
def vega_daily_users_chart_view(request):
    return render(request, "chat/vega_daily_users.html")


@login_required(login_url="/")
@require_http_methods(["GET"])
def vega_daily_messages_chart_view(request):
    return render(request, "chat/vega_daily_messages.html")


def _build_export_filename(prefix, extension):
    timestamp = timezone.localtime().strftime("%Y-%m-%d_%H-%M")
    return f'{prefix}_{timestamp}.{extension}'


def _export_rows_response(rows, export_format, filename_prefix, csv_headers, csv_field_order, json_key):
    if export_format == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{_build_export_filename(filename_prefix, "csv")}"'
        writer = csv.writer(response)
        writer.writerow(csv_headers)
        for row in rows:
            writer.writerow([row[field] for field in csv_field_order])
        return response

    if export_format == "json":
        payload = {
            "generated_at": timezone.now().isoformat(),
            "record_count": len(rows),
            json_key: rows,
        }
        response = JsonResponse(payload, json_dumps_params={"indent": 2})
        response["Content-Disposition"] = f'attachment; filename="{_build_export_filename(filename_prefix, "json")}"'
        return response

    return JsonResponse(
        {
            "error": "invalid_format",
            "message": "format must be csv or json",
        },
        status=400,
        json_dumps_params={"indent": 2},
    )


@login_required(login_url="/")
@require_http_methods(["GET"])
def export_sessions_report(request):
    export_format = (request.GET.get("format", "csv") or "csv").strip().lower()
    query = (request.GET.get("q", "") or "").strip()
    rows = get_session_report_export_rows(request.user, q=query)
    return _export_rows_response(
        rows=rows,
        export_format=export_format,
        filename_prefix="sessions",
        csv_headers=["title", "message_count", "created_at"],
        csv_field_order=["title", "message_count", "created_at"],
        json_key="sessions",
    )


@login_required(login_url="/")
@require_http_methods(["GET"])
def export_memory_bullets_report(request):
    export_format = (request.GET.get("format", "csv") or "csv").strip().lower()
    query = (request.GET.get("q", "") or "").strip()
    rows = get_memory_bullet_report_export_rows(request.user, q=query)
    return _export_rows_response(
        rows=rows,
        export_format=export_format,
        filename_prefix="memory_bullets",
        csv_headers=["content", "memory_type", "created_at"],
        csv_field_order=["content", "memory_type", "created_at"],
        json_key="memory_bullets",
    )




@login_required(login_url="/")
def agent_detail_view(request, agent_id):
    from .agent_service import get_agent_for_user, update_agent_for_user

    agent = get_agent_for_user(request.user, str(agent_id))

    if request.method == "POST":
        fields = {}
        description = request.POST.get("description")
        if description is not None:
            fields["description"] = description.strip()
        if fields:
            agent = update_agent_for_user(request.user, str(agent_id), **fields)
        return redirect("chat:agent_detail", agent_id=agent_id)

    profile = get_or_create_profile_for_user(request.user)
    memory = neo4j.get_or_create_memory(str(profile.pk))
    allBullets = neo4j.get_bullets_for_memory(memory["id"], learner_id=str(profile.pk))
    skillCount = sum(1 for b in allBullets if b.get("isSkill"))
    memoryCount = len(allBullets)
    docs = neo4j.get_documents_for_user(str(profile.pk), agent_id=str(agent_id))
    fileCount = len(docs)
    return render(request, "chat/agent_detail.html", {
        "agent": agent,
        "skill_count": skillCount,
        "memory_count": memoryCount,
        "file_count": fileCount,
    })


@login_required(login_url="/")
@require_http_methods(["POST"])
def agent_delete_view(request, agent_id):
    from .agent_service import delete_agent_for_user
    delete_agent_for_user(request.user, str(agent_id))
    return redirect("chat:my_agent")


@login_required(login_url="/")
def agent_settings_view(request, agent_id):
    from .agent_service import get_agent_for_user, update_agent_for_user

    agent = get_agent_for_user(request.user, str(agent_id))

    if request.method == "POST":
        fields = {}
        systemPrompt = request.POST.get("system_prompt")
        if systemPrompt is not None:
            fields["system_prompt"] = systemPrompt.strip()
        temperature = request.POST.get("temperature")
        if temperature:
            try:
                fields["temperature"] = max(0.0, min(2.0, float(temperature)))
            except ValueError:
                pass
        maxTokens = request.POST.get("max_tokens")
        if maxTokens:
            try:
                fields["max_tokens"] = max(64, min(8192, int(maxTokens)))
            except ValueError:
                pass
        isActive = request.POST.get("is_active")
        if isActive is not None:
            fields["is_active"] = isActive == "on"
        if fields:
            agent = update_agent_for_user(request.user, str(agent_id), **fields)
        return redirect("chat:agent_settings", agent_id=agent_id)

    return render(request, "chat/agent_settings.html", {"agent": agent})


@login_required(login_url="/")
def agent_skills_view(request, agent_id):
    from .agent_service import get_agent_for_user, get_agent_skills

    agent = get_agent_for_user(request.user, str(agent_id))
    groupFilter = (request.GET.get("group") or "").strip()
    enabledOnly = request.GET.get("enabled_only") == "1"
    skills = get_agent_skills(request.user, str(agent_id), enabled_only=enabledOnly)

    if groupFilter:
        skills = [s for s in skills if s.get("skillGroup", "") == groupFilter]

    allSkills = get_agent_skills(request.user, str(agent_id))
    enabledCount = sum(1 for s in allSkills if s.get("skillEnabled"))
    disabledCount = len(allSkills) - enabledCount

    groups = sorted(set(s.get("skillGroup", "") for s in skills if s.get("skillGroup")))

    return render(request, "chat/agent_skills.html", {
        "agent": agent,
        "skills": skills,
        "groups": groups,
        "activeGroup": groupFilter,
        "enabledOnly": enabledOnly,
        "enabled_count": enabledCount,
        "disabled_count": disabledCount,
    })


@login_required(login_url="/")
@require_http_methods(["POST"])
def skill_toggle_view(request, bullet_id):
    from .agent_service import toggle_skill
    enabled = request.POST.get("enabled") == "1"
    result = toggle_skill(request.user, bullet_id, enabled)
    return JsonResponse(result)


@login_required(login_url="/")
def my_agent_redirect_view(request):
    from .agent_service import get_or_create_user_agent
    agent = get_or_create_user_agent(request.user)
    if agent and agent.get("id"):
        return redirect("chat:agent_detail", agent_id=agent["id"])
    return redirect("chat:dashboard")


@login_required(login_url="/")
def agent_files_view(request, agent_id):
    from .agent_service import get_agent_for_user

    MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024

    agent = get_agent_for_user(request.user, str(agent_id))
    profile = get_or_create_profile_for_user(request.user)
    userId = str(profile.pk)

    if request.method == "POST":
        uploaded = request.FILES.get("file")
        if uploaded:
            size = uploaded.size
            if size > MAX_UPLOAD_SIZE_BYTES:
                documents = neo4j.get_documents_for_user(userId, agent_id=str(agent_id))
                return render(request, "chat/agent_files.html", {
                    "agent": agent,
                    "documents": documents,
                    "error": f"File too large. Maximum size: {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB.",
                })

            if size < 1024:
                sizeLabel = f"{size} B"
            elif size < 1024 * 1024:
                sizeLabel = f"{size / 1024:.1f} KB"
            else:
                sizeLabel = f"{size / (1024 * 1024):.1f} MB"

            contentType = getattr(uploaded, "content_type", "")
            imageTypes = {"image/jpeg", "image/png", "image/webp", "image/tiff", "image/bmp"}
            if contentType in imageTypes:
                rawText = "(image file)"
            else:
                rawText = ""
                try:
                    rawText = uploaded.read().decode("utf-8", errors="replace")
                    uploaded.seek(0)
                except Exception:
                    rawText = "(binary file)"

            neo4j.create_document(
                user_id=userId,
                filename=uploaded.name,
                description=request.POST.get("description", ""),
                file_size=sizeLabel,
                raw_text=rawText,
                agent_id=str(agent_id),
            )
        return redirect("chat:agent_files", agent_id=agent_id)

    documents = neo4j.get_documents_for_user(userId, agent_id=str(agent_id))
    return render(request, "chat/agent_files.html", {
        "agent": agent,
        "documents": documents,
    })


@login_required(login_url="/")
@require_http_methods(["POST"])
def agent_file_delete_view(request, agent_id, document_id):
    from .agent_service import get_agent_for_user

    get_agent_for_user(request.user, str(agent_id))
    neo4j.delete_document(str(document_id))
    return redirect("chat:agent_files", agent_id=agent_id)


@login_required(login_url="/")
@require_http_methods(["POST"])
def agent_file_update_description_view(request, agent_id, document_id):
    from .agent_service import get_agent_for_user

    get_agent_for_user(request.user, str(agent_id))
    description = request.POST.get("description", "")
    neo4j.update_document(str(document_id), description=description)
    return redirect("chat:agent_files", agent_id=agent_id)


@login_required(login_url="/")
def agent_memory_view(request, agent_id):
    from .agent_service import get_agent_for_user

    agent = get_agent_for_user(request.user, str(agent_id))
    profile = get_or_create_profile_for_user(request.user)
    memory = neo4j.get_or_create_memory(str(profile.pk))
    bullets = neo4j.get_bullets_for_memory(memory["id"], learner_id=str(profile.pk))
    bullets.sort(key=lambda b: (-b.get("strength", 0), b.get("createdAt", "")), reverse=False)

    return render(request, "chat/agent_memory.html", {
        "agent": agent,
        "bullets": bullets,
    })


@login_required(login_url="/")
@require_http_methods(["POST"])
def memory_vote_view(request, bullet_id):
    VOTE_LIKE = 1
    VOTE_DISLIKE = -1

    direction = request.POST.get("direction", "up")
    newValue = VOTE_LIKE if direction == "up" else VOTE_DISLIKE
    profile = get_or_create_profile_for_user(request.user)
    userId = str(profile.pk)
    bulletIdStr = str(bullet_id)

    bullet = neo4j.get_bullet(bulletIdStr)
    if not bullet:
        return JsonResponse({"error": "Not found"}, status=404)

    existingVote = neo4j.get_user_vote(userId, bulletIdStr)

    helpfulCount = int(bullet.get("helpfulCount", 0))
    harmfulCount = int(bullet.get("harmfulCount", 0))

    if existingVote is None:
        neo4j.upsert_vote(userId, bulletIdStr, newValue)
        if newValue == VOTE_LIKE:
            helpfulCount += 1
        else:
            harmfulCount += 1
    elif existingVote == newValue:
        if existingVote == VOTE_LIKE:
            helpfulCount = max(0, helpfulCount - 1)
        else:
            harmfulCount = max(0, harmfulCount - 1)
        neo4j.delete_vote(userId, bulletIdStr)
        newValue = 0
    else:
        if existingVote == VOTE_LIKE:
            helpfulCount = max(0, helpfulCount - 1)
            harmfulCount += 1
        else:
            harmfulCount = max(0, harmfulCount - 1)
            helpfulCount += 1
        neo4j.upsert_vote(userId, bulletIdStr, newValue)

    def _safeFloat(value, fallback=0.0):
        try:
            result = float(value)
        except (TypeError, ValueError):
            return fallback
        if result != result or result in (float("inf"), float("-inf")):
            return fallback
        return result

    oldStrength = int(_safeFloat(bullet.get("strength"), 0))
    if newValue == VOTE_LIKE:
        strength = min(100, oldStrength + 10)
    elif newValue == VOTE_DISLIKE:
        strength = max(0, oldStrength - 10)
    elif newValue == 0:
        if direction == "up":
            strength = max(0, oldStrength - 10)
        else:
            strength = min(100, oldStrength + 10)
    else:
        strength = oldStrength

    MEMORY_TYPE_MAP = {1: "semantic", 2: "episodic", 3: "procedural"}
    memoryType = int(_safeFloat(bullet.get("memoryType"), 1))
    channel = MEMORY_TYPE_MAP.get(memoryType, "semantic")
    channelKey = f"{channel}_strength"
    oldChannelStrength = _safeFloat(bullet.get(f"{channel}Strength"), 0.0)
    voteAdjust = 15.0 if newValue == VOTE_LIKE else (-15.0 if newValue == VOTE_DISLIKE else ((-15.0 if direction == "up" else 15.0)))
    newChannelStrength = max(0.0, min(100.0, oldChannelStrength + voteAdjust))

    neo4j.update_bullet(
        bulletIdStr,
        helpful_count=helpfulCount,
        harmful_count=harmfulCount,
        strength=strength,
        **{channelKey: round(newChannelStrength, 2)},
    )

    return JsonResponse({
        "bulletId": bulletIdStr,
        "helpful": helpfulCount,
        "harmful": harmfulCount,
        "strength": strength,
        "userVote": newValue,
    })


@login_required(login_url="/")
def dashboard_view(request):
    from .agent_service import get_or_create_user_agent
    from .audit_service import get_activity_feed_for_user

    profile = get_or_create_profile_for_user(request.user)
    userId = str(profile.pk)
    agent = get_or_create_user_agent(request.user)
    activityFeed = get_activity_feed_for_user(request.user, limit=10)
    recentSessions = get_sidebar_sessions_for_user(request.user)[:5]

    allSessions = neo4j.get_sessions_for_user(userId)
    totalSessions = len(allSessions)

    memory = neo4j.get_or_create_memory(userId)
    allBullets = neo4j.get_bullets_for_memory(memory["id"], learner_id=str(profile.pk))
    totalMemories = len(allBullets)

    allSkills = neo4j.get_skills_for_user(userId, enabled_only=True)
    totalSkills = len(allSkills)

    memberSessions = neo4j.get_sessions_for_member(userId)
    totalGroups = sum(1 for s in memberSessions if s.get("accessKey"))

    totalMessages = neo4j.get_total_message_count_for_user(userId)

    return render(request, "chat/dashboard.html", {
        "agent": agent,
        "activityFeed": activityFeed,
        "recentSessions": recentSessions,
        "totalSessions": totalSessions,
        "totalMemories": totalMemories,
        "totalSkills": totalSkills,
        "totalGroups": totalGroups,
        "totalMessages": totalMessages,
    })


@login_required(login_url="/")
def activity_log_view(request):
    from .audit_service import get_audit_log_for_user

    eventType = (request.GET.get("event_type") or "").strip()
    logs = get_audit_log_for_user(request.user, event_type=eventType, limit=200)

    eventTypes = [
        "chat_message", "skill_execution", "memory_update",
        "agent_created", "agent_updated", "agent_deleted",
        "session_created", "skill_toggled",
    ]

    return render(request, "chat/activity_log.html", {
        "logs": logs,
        "eventTypes": eventTypes,
        "activeEventType": eventType,
    })


@login_required(login_url="/")
def admin_settings_view(request):
    if request.method == "POST":
        pass
    return render(request, "chat/admin_settings.html", {})


@login_required(login_url="/")
@require_http_methods(["POST"])
def notification_mark_read_view(request, notification_id):
    from .notification_service import mark_notification_read
    mark_notification_read(request.user, str(notification_id))
    return JsonResponse({"ok": True})


@login_required(login_url="/")
@require_http_methods(["POST"])
def notification_mark_all_read_view(request):
    from .notification_service import mark_all_read
    count = mark_all_read(request.user)
    return JsonResponse({"ok": True, "count": count})


@login_required(login_url="/")
@require_http_methods(["POST"])
def pusher_auth_view(request):
    from app.services import pusher_service

    socketId = request.POST.get("socket_id", "")
    channelName = request.POST.get("channel_name", "")

    if not socketId or not channelName:
        return JsonResponse({"error": "Missing parameters"}, status=400)

    try:
        profile = get_or_create_profile_for_user(request.user)
    except Exception:
        return JsonResponse({"error": "Forbidden"}, status=403)
    userId = str(profile.pk)

    if channelName.startswith("private-group-"):
        sessionId = channelName[len("private-group-"):]
        if not sessionId or not neo4j.user_can_access_session(userId, sessionId):
            _log_pusher_denial(userId, channelName, "no-session-access")
            return JsonResponse({"error": "Forbidden"}, status=403)
    elif channelName.startswith("private-user-"):
        targetUid = channelName[len("private-user-"):]
        if targetUid != userId:
            _log_pusher_denial(userId, channelName, "uid-mismatch")
            return JsonResponse({"error": "Forbidden"}, status=403)
    else:
        _log_pusher_denial(userId, channelName, "unknown-channel")
        return JsonResponse({"error": "Forbidden"}, status=403)

    authResponse = pusher_service.authenticate_channel(channelName, socketId)
    if authResponse is None:
        return JsonResponse({"error": "Auth failed"}, status=403)
    return JsonResponse(authResponse)


def _log_pusher_denial(user_id: str, channel: str, reason: str) -> None:
    try:
        from memoria.event_log import log_event
        log_event(
            "pusher_channel_auth_denied",
            userId=user_id,
            channel=channel,
            reason=reason,
        )
    except Exception:
        pass


@login_required(login_url="/")
@require_http_methods(["POST"])
def typing_view(request, session_id):
    from app.services import pusher_service
    from .agent_service import get_or_create_user_agent
    profile = get_or_create_profile_for_user(request.user)
    agent = get_or_create_user_agent(request.user)
    displayName = agent.name if agent else request.user.username
    pusher_service.send_typing(session_id, profile.pk, displayName)
    return JsonResponse({"ok": True})


@login_required(login_url="/")
@require_http_methods(["POST"])
def stop_typing_view(request, session_id):
    from app.services import pusher_service
    profile = get_or_create_profile_for_user(request.user)
    pusher_service.send_stop_typing(session_id, profile.pk)
    return JsonResponse({"ok": True})


@login_required(login_url="/")
def document_hub_view(request):
    profile = get_or_create_profile_for_user(request.user)
    documents = neo4j.get_documents_for_user(str(profile.pk))
    return render(request, "chat/document_hub.html", {"documents": documents})


@login_required(login_url="/")
def document_upload_view(request):
    from .forms import DocumentUploadForm
    from app.services.ocr import extract_text_from_file, parse_document_fields

    if request.method == "POST":
        form = DocumentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploadedFile = form.cleaned_data["file"]
            ocrResult = extract_text_from_file(uploadedFile)

            if ocrResult.status != "success":
                return render(request, "chat/document_upload.html", {
                    "form": form,
                    "error": ocrResult.error,
                })

            parsedFields = parse_document_fields(ocrResult.raw_text)

            profile = get_or_create_profile_for_user(request.user)

            neo4j.create_document(
                user_id=str(profile.pk),
                filename=uploadedFile.name,
                raw_text=ocrResult.raw_text,
                parsed_fields=parsedFields,
            )

            return render(request, "chat/document_results.html", {
                "ocrResult": ocrResult,
                "parsedFields": parsedFields,
                "bulletCount": 0,
                "lessons": [],
            })
    else:
        form = DocumentUploadForm()

    return render(request, "chat/document_upload.html", {"form": form})


@login_required(login_url="/")
def skill_marketplace_view(request):
    from .skill_catalog import get_all_skills, get_skills_by_category, search_skills, SKILL_CATEGORIES

    categoryFilter = (request.GET.get("category") or "").strip()
    searchQuery = (request.GET.get("q") or "").strip()

    if searchQuery:
        skills = search_skills(searchQuery)
    elif categoryFilter:
        skills = get_skills_by_category(categoryFilter)
    else:
        skills = get_all_skills()

    return render(request, "chat/skill_marketplace.html", {
        "skills": skills,
        "categories": SKILL_CATEGORIES,
        "activeCategory": categoryFilter,
        "searchQuery": searchQuery,
        "totalCount": len(get_all_skills()),
    })


@login_required(login_url="/")
def skill_marketplace_detail_view(request, skill_id):
    from .skill_catalog import get_skill_by_id

    skill = get_skill_by_id(skill_id)
    if skill is None:
        from django.http import Http404
        raise Http404("Skill template not found")

    profile = get_or_create_profile_for_user(request.user)
    allAgents = neo4j.get_agents_for_user(str(profile.pk))
    agents = [a for a in allAgents if a.get("isActive", True)]
    agents.sort(key=lambda a: a.get("name", ""))

    return render(request, "chat/skill_marketplace_detail.html", {
        "skill": skill,
        "agents": agents,
    })


@login_required(login_url="/")
@require_http_methods(["POST"])
def skill_install_view(request, skill_id):
    from .skill_catalog import get_skill_by_id
    from .skill_service import install_template_skill

    templateData = get_skill_by_id(skill_id)
    if templateData is None:
        return JsonResponse({"error": "Skill template not found"}, status=404)

    agentId = (request.POST.get("agent_id") or "").strip()
    profile = get_or_create_profile_for_user(request.user)
    userId = str(profile.pk)

    from django.utils.text import slugify
    candidateSlug = slugify(templateData["name"])[:120]
    existingSkill = neo4j.get_skill_by_slug(userId, candidateSlug)
    if existingSkill:
        return JsonResponse({
            "ok": False,
            "error": "already_installed",
            "message": f"Skill '{templateData['name']}' is already installed.",
        })

    newSkill = install_template_skill(request.user, templateData)

    skillPk = newSkill.get("id", "") if isinstance(newSkill, dict) else getattr(newSkill, "pk", "")

    try:
        from .audit_service import log_audit
        log_audit(
            request.user,
            event_type="skill_installed",
            description=f"Installed template skill: {templateData['name']}",
            metadata={"skillId": templateData["id"], "skillPk": skillPk},
        )
    except Exception:
        pass

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({
            "ok": True,
            "message": f"Skill '{templateData['name']}' installed successfully.",
            "skillId": skillPk,
        })

    if agentId:
        return redirect("chat:agent_skills", agent_id=agentId)
    return redirect("chat:skill_marketplace")








@login_required(login_url="/")
@require_http_methods(["POST"])
def agent_start_chat_view(request, template_id):
    from .agent_catalog import get_template_agent_by_id as get_template_agent

    template = get_template_agent(template_id)
    if not template:
        return redirect("chat:agent_marketplace")

    profile = get_or_create_profile_for_user(request.user)
    userId = str(profile.pk)
    agentTitle = f"Chat with {template['name']}"

    allSessions = neo4j.get_sessions_for_user(userId)
    existing = None
    for s in allSessions:
        if s.get("title") == agentTitle and not s.get("accessKey"):
            existing = s
            break

    if existing:
        return redirect("chat:conversation_detail", session_id=existing["id"])

    from .write_service import create_session_with_outbox, create_message_with_outbox
    session = create_session_with_outbox(userId, agentTitle)
    create_message_with_outbox(
        session["id"],
        f"Hi! I'm {template['name']}. {template['description']} How can I help you?",
        userId,
        role="assistant",
        sender_agent_name=template["name"],
    )

    return redirect("chat:conversation_detail", session_id=session["id"])


@login_required(login_url="/")
def agent_marketplace_view(request):
    from .agent_catalog import get_all_template_agents, get_template_agents_by_category, search_template_agents, AGENT_CATEGORIES

    categoryFilter = (request.GET.get("category") or "").strip()
    searchQuery = (request.GET.get("q") or "").strip()

    if searchQuery:
        agents = search_template_agents(searchQuery)
    elif categoryFilter:
        agents = get_template_agents_by_category(categoryFilter)
    else:
        agents = get_all_template_agents()

    return render(request, "chat/agent_marketplace.html", {
        "templateAgents": agents,
        "categories": AGENT_CATEGORIES,
        "activeCategory": categoryFilter,
        "searchQuery": searchQuery,
        "totalCount": len(get_all_template_agents()),
    })


@login_required(login_url="/")
def agent_marketplace_detail_view(request, template_id):
    from .agent_catalog import get_template_agent_by_id

    template = get_template_agent_by_id(template_id)
    if template is None:
        from django.http import Http404
        raise Http404("Agent template not found")

    return render(request, "chat/agent_marketplace_detail.html", {"template": template})


@login_required(login_url="/")
def group_list_view(request):
    profile = get_or_create_profile_for_user(request.user)
    userId = str(profile.pk)
    memberSessions = neo4j.get_sessions_for_member(userId)
    groups = []
    for s in memberSessions:
        if not s.get("accessKey"):
            continue
        sessionId = s.get("id", "")
        groups.append({
            "id": sessionId,
            "title": s.get("title", ""),
            "description": s.get("description", ""),
            "access_key": s.get("accessKey", ""),
            "member_count": s.get("memberCount", 0),
            "role": s.get("memberRole", "member"),
            "url": f"/chat/c/{sessionId}/",
        })
    return render(request, "chat/group_list.html", {"groups": groups})


@login_required(login_url="/")
@require_http_methods(["POST"])
def new_chat_view(request):
    from .write_service import create_session_with_outbox
    profile = get_or_create_profile_for_user(request.user)
    session = create_session_with_outbox(str(profile.pk), "New Chat")
    return redirect(f"/chat/c/{session['id']}/")


@login_required(login_url="/")
@require_http_methods(["POST"])
def group_create_view(request):
    import uuid
    profile = get_or_create_profile_for_user(request.user)
    userId = str(profile.pk)
    title = request.POST.get("title", "").strip()
    description = request.POST.get("description", "").strip()
    accessKey = request.POST.get("access_key", "").strip()
    if not title:
        return redirect("memoria:home")
    if not accessKey:
        accessKey = uuid.uuid4().hex[:12]
    existingSession = neo4j.get_session_by_access_key(accessKey)
    if existingSession:
        accessKey = uuid.uuid4().hex[:12]
    from .write_service import create_session_with_outbox, update_session_with_outbox
    session = create_session_with_outbox(userId, title)
    sessionId = session["id"]
    update_session_with_outbox(sessionId, description=description, access_key=accessKey)
    try:
        from app.services import pusher_service
        pusher_service.send_member_joined(sessionId, {
            "userId": userId,
            "userName": request.user.username,
            "role": "admin",
        })
    except Exception:
        pass
    return redirect("chat:conversation_detail", session_id=sessionId)


@login_required(login_url="/")
@require_http_methods(["POST"])
def group_join_view(request):
    profile = get_or_create_profile_for_user(request.user)
    userId = str(profile.pk)
    accessKey = request.POST.get("access_key", "").strip()
    if not accessKey:
        return redirect("memoria:home")
    session = neo4j.get_session_by_access_key(accessKey)
    if not session:
        return redirect("memoria:home")
    sessionId = session["id"]
    members = neo4j.get_members_for_session(sessionId)
    isAlreadyMember = any(str(m.get("userId", "")) == userId for m in members)
    if isAlreadyMember:
        return redirect("chat:conversation_detail", session_id=sessionId)
    neo4j.add_member_to_session(sessionId, userId, role="member")
    try:
        from app.services import pusher_service
        pusher_service.send_member_joined(sessionId, {
            "userId": userId,
            "userName": request.user.username,
            "role": "member",
        })
    except Exception:
        pass
    from django.contrib import messages as django_messages
    sessionTitle = session.get("title", "")
    django_messages.success(request, f"You joined \"{sessionTitle}\"")
    try:
        from .notification_service import create_notification
        from .models.notification import NotificationType
        sessionUrl = f"/chat/c/{sessionId}/"
        create_notification(
            request.user,
            title=f"Joined group: {sessionTitle}",
            message=f"You are now a member of {sessionTitle}.",
            notification_type=NotificationType.SYSTEM_ALERT,
            related_url=sessionUrl,
        )
        adminMembers = [m for m in members if m.get("role") == "admin"]
        for adminMember in adminMembers:
            adminUserId = adminMember.get("userId")
            if adminUserId:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                try:
                    adminUser = User.objects.get(pk=adminUserId)
                    displayName = getattr(profile, "display_name", "") or request.user.username
                    create_notification(
                        adminUser,
                        title=f"{displayName} joined your group",
                        message=f"A new member joined {sessionTitle}.",
                        notification_type=NotificationType.SYSTEM_ALERT,
                        related_url=sessionUrl,
                    )
                except User.DoesNotExist:
                    pass
    except Exception:
        pass
    return redirect("chat:conversation_detail", session_id=sessionId)


@login_required(login_url="/")
@require_http_methods(["POST"])
def group_leave_view(request, session_id):
    profile = get_or_create_profile_for_user(request.user)
    userId = str(profile.pk)
    sessionIdStr = str(session_id)
    members = neo4j.get_members_for_session(sessionIdStr)
    isMember = any(str(m.get("userId", "")) == userId for m in members)
    if not isMember:
        return redirect("memoria:home")
    neo4j.remove_member_from_session(sessionIdStr, userId)
    try:
        from app.services import pusher_service
        pusher_service.send_member_left(sessionIdStr, {
            "userId": userId,
            "userName": request.user.username,
        })
    except Exception:
        pass
    remainingCount = neo4j.count_session_members(sessionIdStr)
    if remainingCount == 0:
        from .write_service import delete_session_with_outbox
        delete_session_with_outbox(sessionIdStr)
    return redirect("memoria:home")


@login_required(login_url="/")
def group_settings_view(request, session_id):
    profile = get_or_create_profile_for_user(request.user)
    userId = str(profile.pk)
    sessionIdStr = str(session_id)
    session = neo4j.get_session_by_id(sessionIdStr)
    if session is None:
        raise Http404
    members = neo4j.get_members_for_session(sessionIdStr)
    isAdmin = any(
        str(m.get("userId", "")) == userId and m.get("role") == "admin"
        for m in members
    )
    if not isAdmin:
        raise Http404

    if request.method == "POST":
        from .write_service import update_session_with_outbox, delete_session_with_outbox
        action = request.POST.get("action", "")
        if action == "disband":
            delete_session_with_outbox(sessionIdStr)
            return redirect("memoria:home")
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        updateKwargs = {}
        if title:
            updateKwargs["title"] = title[:200]
        updateKwargs["description"] = description
        update_session_with_outbox(sessionIdStr, **updateKwargs)
        return redirect("chat:group_settings", session_id=session_id)

    return render(request, "chat/group_settings.html", {
        "session": session,
        "members": members,
        "is_admin": True,
    })



