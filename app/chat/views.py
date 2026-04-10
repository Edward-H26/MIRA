import csv
import json
import time

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.views import View
from django.views.decorators.http import require_http_methods
from django.views.generic import DetailView, ListView

from memoria.event_log import log_event
from .models import Memory, MemoryBullet
from .service import (
    stream_user_message_with_agent_reply,
    get_analytics_dashboard_context_with_reports,
    get_or_create_profile_for_user,
    get_memory_list_data,
    get_memory_bullet_report_export_rows,
    get_memory_strength_chart_png,
    get_memory_summary,
    get_memory_type_chart_png,
    get_activity_chart_png,
    get_session_report_export_rows,
    get_session_for_user,
    get_session_for_user_or_member,
    get_sidebar_sessions_for_user,
    get_latency_over_time_chart_png,
    get_latency_by_model_chart_png,
    get_error_rate_chart_png,
    get_daily_cost_chart_png,
    get_token_usage_chart_png,
    get_cost_by_model_chart_png,
    get_request_log_export_rows,
)

PENDING_PROMPT_SESSION_KEY = "pending_chat_prompts"


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
        from .models.memory_vote import MemoryVote
        profile = get_or_create_profile_for_user(self.request.user)
        userVotes = {
            v["bullet_id"]: v["value"]
            for v in MemoryVote.objects.filter(user=profile).values("bullet_id", "value")
        }
        context["user_votes"] = userVotes
        return context


@method_decorator(login_required(login_url="/"), name="dispatch")
class ConversationMessagesView(View):
    def get(self, request, session_id):
        try:
            session = get_session_for_user(request.user, session_id, with_messages=True)
        except Http404:
            from .models import Session, SessionMember
            session = get_object_or_404(Session, pk=session_id)
            profile = get_or_create_profile_for_user(request.user)
            if not SessionMember.objects.filter(session=session, user=profile).exists():
                raise Http404
        is_generating = session.ensure_generation_lock_fresh()
        pending_prompts = dict(request.session.get(PENDING_PROMPT_SESSION_KEY, {}))
        pending_prompt = pending_prompts.pop(str(session.pk), "")
        if pending_prompts:
            request.session[PENDING_PROMPT_SESSION_KEY] = pending_prompts
        else:
            request.session.pop(PENDING_PROMPT_SESSION_KEY, None)
        if pending_prompt:
            request.session.modified = True
        return render(
            request,
            "chat/conversation_detail.html",
            {
                "session": session,
                "pending_prompt": pending_prompt,
                "generation_in_progress": is_generating,
            },
        )

    def post(self, request, session_id):
        session = get_session_for_user(request.user, session_id)
        content = (request.POST.get("message") or "").strip()
        if not content:
            return JsonResponse({"error": "Empty message"}, status=400)
        log_event("chat_message_submit", request=request, session_id=session.pk)
        if not session.acquire_generation_lock():
            log_event("chat_generation_rejected_locked", request=request, session_id=session.pk)
            return JsonResponse(
                {"error": "generation_in_progress", "message": "Previous response is still generating."},
                status=409,
            )

        autoTitle = None
        if session.title in ("New Chat", "") and not session.messages.exists():
            autoTitle = content[:60].strip()
            if autoTitle:
                session.title = autoTitle
                session.save(update_fields=["title"])

        if request.headers.get("x-requested-with") != "XMLHttpRequest":
            try:
                for _ in stream_user_message_with_agent_reply(session, content):
                    pass
            finally:
                session.release_generation_lock()
            return redirect(session.get_absolute_url())

        def event_stream():
            titleInjected = not autoTitle
            try:
                for payload in stream_user_message_with_agent_reply(session, content):
                    if not titleInjected:
                        payload = {**payload, "auto_title": autoTitle, "session_id": session.pk}
                        titleInjected = True
                    yield json.dumps(payload, ensure_ascii=False) + "\n"
            finally:
                session.release_generation_lock()

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
    from .models import Message
    from .models.message import Role

    session = get_session_for_user(request.user, session_id)
    try:
        msg = Message.objects.get(pk=message_id, session=session, role=Role.USER)
    except Message.DoesNotExist:
        return JsonResponse({"error": "Message not found"}, status=404)

    content = (request.POST.get("content") or "").strip()
    if not content:
        return JsonResponse({"error": "Content required"}, status=400)

    msg.content = content
    msg.save(update_fields=["content"])
    return JsonResponse({"ok": True, "content": msg.content})


@login_required(login_url="/")
@require_http_methods(["POST"])
def message_resend_view(request, session_id, message_id):
    from .models import Message
    from .models.message import Role

    session = get_session_for_user(request.user, session_id)
    try:
        msg = Message.objects.get(pk=message_id, session=session, role=Role.USER)
    except Message.DoesNotExist:
        return JsonResponse({"error": "Message not found"}, status=404)

    if not session.acquire_generation_lock():
        return JsonResponse({"error": "generation_in_progress"}, status=409)

    Message.objects.filter(session=session, created_at__gt=msg.created_at).delete()

    def event_stream():
        try:
            for payload in stream_user_message_with_agent_reply(session, msg.content, skip_user_message=True):
                yield json.dumps(payload, ensure_ascii=False) + "\n"
        finally:
            session.release_generation_lock()

    response = StreamingHttpResponse(
        event_stream(),
        content_type="application/x-ndjson; charset=utf-8",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required(login_url="/")
@require_http_methods(["POST"])
def conversation_upload_view(request, session_id):
    session = get_session_for_user(request.user, session_id)

    uploadedFile = request.FILES.get("file")
    if not uploadedFile:
        return JsonResponse({"error": "No file uploaded"}, status=400)

    from app.services.ocr import validate_uploaded_image, extract_text_from_file

    isValid, errorMsg = validate_uploaded_image(uploadedFile)
    if not isValid:
        return JsonResponse({"error": errorMsg}, status=400)

    try:
        ocrResult = extract_text_from_file(uploadedFile)
    except Exception as exc:
        log_event("chat_upload_ocr_crash", session_id=session.pk, error=str(exc))
        return JsonResponse({"error": f"Document processing failed: {exc}"}, status=400)

    if ocrResult.status != "success":
        return JsonResponse({"error": ocrResult.error or "OCR extraction failed"}, status=400)

    userMessage = (request.POST.get("message") or "").strip()
    truncatedText = ocrResult.raw_text[:500]

    displayContent = userMessage or f"Analyze this document"
    displayContent += f"\n[Attached: {uploadedFile.name}]"

    aiPromptParts = []
    if userMessage:
        aiPromptParts.append(userMessage)
    aiPromptParts.append(
        f"[Uploaded document: {uploadedFile.name}]\n\n"
        f"Extracted text:\n{truncatedText}"
    )
    aiPrompt = "\n\n".join(aiPromptParts)

    log_event("chat_document_upload", request=request, session_id=session.pk)

    if not session.acquire_generation_lock():
        return JsonResponse({"error": "generation_in_progress"}, status=409)

    from .models import Message
    from .models.message import Role
    Message.objects.create(session=session, role=Role.USER, content=displayContent)

    def event_stream():
        try:
            for payload in stream_user_message_with_agent_reply(session, aiPrompt, skip_user_message=True):
                yield json.dumps(payload, ensure_ascii=False) + "\n"
        finally:
            session.release_generation_lock()

    response = StreamingHttpResponse(
        event_stream(),
        content_type="application/x-ndjson; charset=utf-8",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


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
@require_http_methods(["GET"])
def conversation_lock_status_view(request, session_id):
    session = get_session_for_user(request.user, session_id)
    is_generating = session.ensure_generation_lock_fresh()
    return JsonResponse(
        {
            "session_id": session.pk,
            "generation_in_progress": is_generating,
            "generation_started_at": session.generation_started_at.isoformat() if session.generation_started_at else None,
            "updated_at": session.updated_at.isoformat(),
        }
    )


@login_required(login_url="/")
@require_http_methods(["GET"])
def conversation_wait_for_unlock_view(request, session_id):
    session = get_session_for_user(request.user, session_id)
    try:
        timeout_seconds = int(request.GET.get("timeout", "55"))
    except (TypeError, ValueError):
        timeout_seconds = 55
    timeout_seconds = min(max(timeout_seconds, 5), 120)

    deadline = time.monotonic() + timeout_seconds
    while True:
        session.refresh_from_db(fields=["generation_in_progress", "generation_started_at", "updated_at"])
        is_generating = session.ensure_generation_lock_fresh()
        if not is_generating:
            return JsonResponse(
                {
                    "session_id": session.pk,
                    "generation_in_progress": False,
                    "timed_out": False,
                }
            )
        if time.monotonic() >= deadline:
            return JsonResponse(
                {
                    "session_id": session.pk,
                    "generation_in_progress": True,
                    "timed_out": True,
                }
            )
        time.sleep(0.5)


@login_required(login_url="/")
@require_http_methods(["POST"])
def session_rename_view(request, session_id):
    session = get_session_for_user_or_member(request.user, session_id, require_admin=True)
    title = (request.POST.get("title") or "").strip()
    if not title:
        return JsonResponse({"error": "Title is required"}, status=400)
    session.title = title[:200]
    session.save(update_fields=["title"])
    log_event("chat_session_updated", request=request, session_id=session.pk, action="rename")
    return JsonResponse({"ok": True, "title": session.title})


@login_required(login_url="/")
@require_http_methods(["POST"])
def session_delete_view(request, session_id):
    session = get_session_for_user(request.user, session_id)
    deleted_id = session.pk
    session.delete()
    log_event("chat_session_updated", request=request, session_id=deleted_id, action="delete")
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


@require_http_methods(["GET"])
def vega_daily_users_chart_view(request):
    return render(request, "chat/vega_daily_users.html")


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
    from .models import Document
    skillCount = MemoryBullet.objects.filter(memory__user=profile, is_skill=True).count()
    memoryCount = MemoryBullet.objects.filter(memory__user=profile).count()
    fileCount = Document.objects.filter(user=profile, agent_id=agent_id).count()
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
    from .agent_service import get_agents_for_user
    agents = get_agents_for_user(request.user)
    if agents:
        return redirect("chat:agent_detail", agent_id=agents[0]["id"])
    return redirect("chat:dashboard")


@login_required(login_url="/")
def agent_files_view(request, agent_id):
    from .agent_service import get_agent_for_user
    from .models import Document

    agent = get_agent_for_user(request.user, str(agent_id))
    profile = request.user.profile

    if request.method == "POST":
        from .models.document import MAX_UPLOAD_SIZE_BYTES
        uploaded = request.FILES.get("file")
        if uploaded:
            size = uploaded.size
            if size > MAX_UPLOAD_SIZE_BYTES:
                documents = Document.objects.filter(user=profile, agent_id=agent_id)
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

            Document.objects.create(
                user=profile,
                agent_id=agent_id,
                filename=uploaded.name,
                description=request.POST.get("description", ""),
                file=uploaded,
                file_size=sizeLabel,
                raw_text=rawText,
                ttl_days=None,
            )
        return redirect("chat:agent_files", agent_id=agent_id)

    documents = Document.objects.filter(user=profile, agent_id=agent_id)
    return render(request, "chat/agent_files.html", {
        "agent": agent,
        "documents": documents,
    })


@login_required(login_url="/")
@require_http_methods(["POST"])
def agent_file_delete_view(request, agent_id, document_id):
    from .agent_service import get_agent_for_user
    from .models import Document

    get_agent_for_user(request.user, str(agent_id))
    profile = request.user.profile
    Document.objects.filter(id=document_id, user=profile, agent_id=agent_id).delete()
    return redirect("chat:agent_files", agent_id=agent_id)


@login_required(login_url="/")
@require_http_methods(["POST"])
def agent_file_update_description_view(request, agent_id, document_id):
    from .agent_service import get_agent_for_user
    from .models import Document

    get_agent_for_user(request.user, str(agent_id))
    profile = request.user.profile
    description = request.POST.get("description", "")
    Document.objects.filter(id=document_id, user=profile, agent_id=agent_id).update(description=description)
    return redirect("chat:agent_files", agent_id=agent_id)


@login_required(login_url="/")
def agent_memory_view(request, agent_id):
    from .agent_service import get_agent_for_user

    agent = get_agent_for_user(request.user, str(agent_id))
    profile = request.user.profile
    bullets = MemoryBullet.objects.filter(memory__user=profile).order_by("-strength", "-created_at")

    return render(request, "chat/agent_memory.html", {
        "agent": agent,
        "bullets": bullets,
    })


@login_required(login_url="/")
@require_http_methods(["POST"])
def memory_vote_view(request, bullet_id):
    from .models.memory_vote import MemoryVote, VoteValue

    direction = request.POST.get("direction", "up")
    newValue = VoteValue.LIKE if direction == "up" else VoteValue.DISLIKE
    profile = request.user.profile
    bullet = MemoryBullet.objects.filter(id=bullet_id, memory__user=profile).first()
    if not bullet:
        return JsonResponse({"error": "Not found"}, status=404)

    existing = MemoryVote.objects.filter(user=profile, bullet=bullet).first()

    if existing is None:
        MemoryVote.objects.create(user=profile, bullet=bullet, value=newValue)
        if newValue == VoteValue.LIKE:
            bullet.helpful_count += 1
        else:
            bullet.harmful_count += 1
    elif existing.value == newValue:
        if existing.value == VoteValue.LIKE:
            bullet.helpful_count = max(0, bullet.helpful_count - 1)
        else:
            bullet.harmful_count = max(0, bullet.harmful_count - 1)
        existing.delete()
        newValue = 0
    else:
        if existing.value == VoteValue.LIKE:
            bullet.helpful_count = max(0, bullet.helpful_count - 1)
            bullet.harmful_count += 1
        else:
            bullet.harmful_count = max(0, bullet.harmful_count - 1)
            bullet.helpful_count += 1
        existing.value = newValue
        existing.save(update_fields=["value", "updated_at"])

    oldStrength = bullet.strength
    if newValue == VoteValue.LIKE:
        bullet.strength = min(100, oldStrength + 10)
    elif newValue == VoteValue.DISLIKE:
        bullet.strength = max(0, oldStrength - 10)
    elif newValue == 0:
        if direction == "up":
            bullet.strength = max(0, oldStrength - 10)
        else:
            bullet.strength = min(100, oldStrength + 10)
    bullet.save(update_fields=["helpful_count", "harmful_count", "strength"])

    return JsonResponse({
        "bulletId": bullet.pk,
        "helpful": bullet.helpful_count,
        "harmful": bullet.harmful_count,
        "strength": bullet.strength,
        "userVote": newValue,
    })


@login_required(login_url="/")
def dashboard_view(request):
    from .agent_service import get_or_create_user_agent
    from .audit_service import get_activity_feed_for_user
    from .models import Session, SessionMember, Message as Msg
    from .models.skill import Skill

    profile = get_or_create_profile_for_user(request.user)
    agent = get_or_create_user_agent(request.user)
    activityFeed = get_activity_feed_for_user(request.user, limit=10)
    recentSessions = get_sidebar_sessions_for_user(request.user)[:5]

    totalSessions = Session.objects.filter(user=profile).count()
    totalMemories = MemoryBullet.objects.filter(memory__user=profile).count()
    totalSkills = Skill.objects.filter(user=profile, is_enabled=True).count()
    totalGroups = SessionMember.objects.filter(
        user=profile, session__access_key__isnull=False,
    ).exclude(session__access_key="").count()
    totalMessages = Msg.objects.filter(session__user=profile).count()

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

    authResponse = pusher_service.authenticate_channel(channelName, socketId)
    if authResponse is None:
        return JsonResponse({"error": "Auth failed"}, status=403)
    return JsonResponse(authResponse)


@login_required(login_url="/")
@require_http_methods(["POST"])
def typing_view(request, session_id):
    from app.services import pusher_service
    profile = get_or_create_profile_for_user(request.user)
    pusher_service.send_typing(session_id, profile.pk, request.user.username)
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
    from .models import Document
    profile = get_or_create_profile_for_user(request.user)
    documents = Document.objects.filter(user=profile)
    return render(request, "chat/document_hub.html", {"documents": documents})


@login_required(login_url="/")
def document_upload_view(request):
    from .forms import DocumentUploadForm
    from .models import Document
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

            Document.objects.create(
                user=profile,
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
    from .models.agent import Agent
    agents = Agent.objects.filter(user=profile, is_active=True).order_by("name")

    return render(request, "chat/skill_marketplace_detail.html", {
        "skill": skill,
        "agents": agents,
    })


@login_required(login_url="/")
@require_http_methods(["POST"])
def skill_install_view(request, skill_id):
    from .skill_catalog import get_skill_by_id
    from .skill_service import install_template_skill
    from .models.skill import Skill

    templateData = get_skill_by_id(skill_id)
    if templateData is None:
        return JsonResponse({"error": "Skill template not found"}, status=404)

    agentId = (request.POST.get("agent_id") or "").strip()
    profile = get_or_create_profile_for_user(request.user)

    from django.utils.text import slugify
    candidateSlug = slugify(templateData["name"])[:120]
    if Skill.objects.filter(user=profile, slug=candidateSlug).exists():
        return JsonResponse({
            "ok": False,
            "error": "already_installed",
            "message": f"Skill '{templateData['name']}' is already installed.",
        })

    newSkill = install_template_skill(request.user, templateData)

    try:
        from .audit_service import log_audit
        log_audit(
            request.user,
            event_type="skill_installed",
            description=f"Installed template skill: {templateData['name']}",
            metadata={"skillId": templateData["id"], "skillPk": newSkill.pk},
        )
    except Exception:
        pass

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({
            "ok": True,
            "message": f"Skill '{templateData['name']}' installed successfully.",
            "skillId": newSkill.pk,
        })

    if agentId:
        return redirect("chat:agent_skills", agent_id=agentId)
    return redirect("chat:skill_marketplace")








@login_required(login_url="/")
@require_http_methods(["POST"])
def agent_start_chat_view(request, template_id):
    from .agent_catalog import get_template_agent_by_id as get_template_agent
    from .models import Session, Message
    from .models.message import Role

    template = get_template_agent(template_id)
    if not template:
        return redirect("chat:agent_marketplace")

    profile = get_or_create_profile_for_user(request.user)
    agentTitle = f"Chat with {template['name']}"

    existing = Session.objects.filter(
        user=profile,
        title=agentTitle,
        access_key__isnull=True,
    ).order_by("-updated_at").first()

    if existing:
        return redirect("chat:conversation_detail", session_id=existing.id)

    session = Session.objects.create(user=profile, title=agentTitle)
    Message.objects.create(
        session=session,
        role=Role.ASSISTANT,
        content=f"Hi! I'm {template['name']}. {template['description']} How can I help you?",
        sender_agent_name=template["name"],
    )

    return redirect("chat:conversation_detail", session_id=session.id)


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
    from .models import SessionMember
    profile = get_or_create_profile_for_user(request.user)
    memberships = SessionMember.objects.filter(user=profile).select_related("session")
    groups = []
    for m in memberships:
        s = m.session
        groups.append({
            "id": s.pk,
            "title": s.title,
            "description": s.description,
            "access_key": s.access_key,
            "member_count": s.members.count(),
            "role": m.role,
            "url": s.get_absolute_url(),
        })
    return render(request, "chat/group_list.html", {"groups": groups})


@login_required(login_url="/")
@require_http_methods(["POST"])
def new_chat_view(request):
    from .models import Session
    profile = get_or_create_profile_for_user(request.user)
    session = Session.objects.create(user=profile, title="New Chat")
    return redirect(session.get_absolute_url())


@login_required(login_url="/")
@require_http_methods(["POST"])
def group_create_view(request):
    import uuid
    from .models import Session, SessionMember
    profile = get_or_create_profile_for_user(request.user)
    title = request.POST.get("title", "").strip()
    description = request.POST.get("description", "").strip()
    access_key = request.POST.get("access_key", "").strip()
    if not title:
        return redirect("memoria:home")
    if not access_key:
        access_key = uuid.uuid4().hex[:12]
    if Session.objects.filter(access_key=access_key).exists():
        access_key = uuid.uuid4().hex[:12]
    session = Session.objects.create(
        user=profile, title=title, description=description,
        access_key=access_key,
    )
    SessionMember.objects.create(session=session, user=profile, role=SessionMember.ROLE_ADMIN)
    try:
        from app.services import pusher_service
        pusher_service.send_member_joined(session.pk, {
            "userId": profile.pk,
            "userName": request.user.username,
            "role": "admin",
        })
    except Exception:
        pass
    return redirect("chat:conversation_detail", session_id=session.id)


@login_required(login_url="/")
@require_http_methods(["POST"])
def group_join_view(request):
    from .models import Session, SessionMember
    profile = get_or_create_profile_for_user(request.user)
    access_key = request.POST.get("access_key", "").strip()
    if not access_key:
        return redirect("memoria:home")
    session = Session.objects.filter(access_key=access_key).first()
    if not session:
        return redirect("memoria:home")
    if SessionMember.objects.filter(session=session, user=profile).exists():
        return redirect("chat:conversation_detail", session_id=session.pk)
    SessionMember.objects.create(session=session, user=profile, role=SessionMember.ROLE_MEMBER)
    try:
        from app.services import pusher_service
        pusher_service.send_member_joined(session.pk, {
            "userId": profile.pk,
            "userName": request.user.username,
            "role": "member",
        })
    except Exception:
        pass
    from django.contrib import messages as django_messages
    django_messages.success(request, f"You joined \"{session.title}\"")
    try:
        from .notification_service import create_notification
        from .models.notification import NotificationType
        create_notification(
            request.user,
            title=f"Joined group: {session.title}",
            message=f"You are now a member of {session.title}.",
            notification_type=NotificationType.SYSTEM_ALERT,
            related_url=session.get_absolute_url(),
        )
        adminMembers = SessionMember.objects.filter(session=session, role=SessionMember.ROLE_ADMIN)
        for adminMember in adminMembers:
            create_notification(
                adminMember.user.user,
                title=f"{profile.display_name or request.user.username} joined your group",
                message=f"A new member joined {session.title}.",
                notification_type=NotificationType.SYSTEM_ALERT,
                related_url=session.get_absolute_url(),
            )
    except Exception:
        pass
    return redirect("chat:conversation_detail", session_id=session.pk)


@login_required(login_url="/")
@require_http_methods(["POST"])
def group_leave_view(request, session_id):
    from .models import Session, SessionMember
    profile = get_or_create_profile_for_user(request.user)
    membership = SessionMember.objects.filter(session_id=session_id, user=profile).first()
    if not membership:
        return redirect("memoria:home")
    membership.delete()
    try:
        from app.services import pusher_service
        pusher_service.send_member_left(session_id, {
            "userId": profile.pk,
            "userName": request.user.username,
        })
    except Exception:
        pass
    remainingCount = SessionMember.objects.filter(session_id=session_id).count()
    if remainingCount == 0:
        Session.objects.filter(pk=session_id).delete()
    return redirect("memoria:home")


@login_required(login_url="/")
def group_settings_view(request, session_id):
    from .models import Session, SessionMember
    profile = get_or_create_profile_for_user(request.user)
    session = get_object_or_404(Session, pk=session_id)
    membership = SessionMember.objects.filter(session=session, user=profile, role=SessionMember.ROLE_ADMIN).first()
    if not membership:
        raise Http404

    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "disband":
            session.delete()
            return redirect("memoria:home")
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        updateFields = []
        if title:
            session.title = title[:200]
            updateFields.append("title")
        session.description = description
        updateFields.append("description")
        if updateFields:
            session.save(update_fields=updateFields)
        return redirect("chat:group_settings", session_id=session_id)

    members = SessionMember.objects.filter(session=session).select_related("user", "user__user")
    return render(request, "chat/group_settings.html", {
        "session": session,
        "members": members,
        "is_admin": True,
    })



