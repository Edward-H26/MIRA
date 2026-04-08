import io
import os
import re
import time
from datetime import timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from django.db.models import Avg, Count, ExpressionWrapper, F, IntegerField, Max, Min, Prefetch, Sum
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek
from django.http import Http404
from django.utils import timezone

import math

from memoria.event_log import log_event
from app.services.gemini import generate_reply_stream, classify_prompt as gemini_classify
from app.services.classifier import classify_prompt as regex_classify
from app.services import local_llm
from app.services.gemini import generate_reply_text
from .ace_runtime import run_ace_chat_turn, guidance_from_bullets
from .rendering import render_assistant_markdown_html
from .models import Memory, Message, MemoryBullet, Session
from .models.message import Role
from app.users.models import UserProfile as Profile

PROGRESSIVE_COLORS = ["#575BEF", "#6F82FF", "#8DA0FF", "#AEBBFF", "#D6DDFF"]
SEGMENT_COLORS = ["#9698FF", "#664FA1", "#FFC5D6", "#DAC6FF", "#B4EDE4"]
CHART_BG = "#F7F8FF"
CHART_GRID = "#DCE1FF"
CHART_TEXT = "#2F3A4A"
CHART_MUTED = "#6A7290"
LOCAL_PREPROCESS_CONTEXT_MAX_MESSAGES = 6
INITIAL_STREAM_CHUNK_SIZE = 5
FALLBACK_TEXT = "Sorry, I couldn't reach the AI service just now."


def retrieve_relevant_document_chunks(user_profile, query, agent_id=None, top_k=5):
    from .models import Document
    try:
        from app.services import embedding as embedding_service
        if not embedding_service.is_available():
            return []
    except Exception:
        return []

    docs = Document.objects.filter(user=user_profile)
    if agent_id:
        docs = docs.filter(agent_id=agent_id)
    docs = list(docs)
    if not docs:
        return []

    all_chunks = []
    for doc in docs:
        if not doc.raw_text or len(doc.raw_text.strip()) < 20:
            continue
        cached = doc.parsed_fields.get("chunk_embeddings") if isinstance(doc.parsed_fields, dict) else None
        if cached:
            for item in cached:
                all_chunks.append({"filename": doc.filename, "text": item["text"], "embedding": item["embedding"]})
        else:
            text = doc.raw_text
            chunk_size = 500
            overlap = 50
            chunks = []
            for i in range(0, len(text), chunk_size - overlap):
                chunk = text[i:i + chunk_size].strip()
                if len(chunk) > 20:
                    chunks.append(chunk)
            if chunks:
                try:
                    embeddings = embedding_service.encode_texts(chunks)
                    for idx, chunk in enumerate(chunks):
                        all_chunks.append({"filename": doc.filename, "text": chunk, "embedding": embeddings[idx].tolist()})
                except Exception:
                    for chunk in chunks:
                        all_chunks.append({"filename": doc.filename, "text": chunk, "embedding": None})

    if not all_chunks:
        return []

    try:
        import numpy as np
        query_emb = embedding_service.encode_query(query)
        valid_chunks = [c for c in all_chunks if c["embedding"] is not None]
        if not valid_chunks:
            return []
        corpus = np.array([c["embedding"] for c in valid_chunks])
        results = embedding_service.cosine_search(query_emb, corpus, top_k=top_k)
        return [{"filename": valid_chunks[idx]["filename"], "chunk": valid_chunks[idx]["text"], "similarity": float(score)} for idx, score in results if score > 0.2]
    except Exception:
        return []


def _is_stream_debug_enabled():
    return (os.getenv("CHAT_STREAM_DEBUG", "0") or "").strip().lower() in {"1", "true", "yes", "on"}


def _stream_debug_log(message):
    if _is_stream_debug_enabled():
        log_event("chat_stream_debug", message=message)


def _safe_env_bool(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _safe_env_int(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except Exception:
        return default
    return parsed if parsed > 0 else default


def _build_conversation_context(session, max_messages=12):
    messages = list(
        Message.objects.filter(session=session)
        .order_by("-created_at")[:max_messages]
    )
    messages.reverse()
    lines = []
    for msg in messages:
        role = "User" if msg.role == 2 else "Assistant"
        if msg.role != 1:
            lines.append(f"{role}: {msg.content[:500]}")
    return "\n".join(lines[-max_messages:])


def _build_guidance_from_bullets(bullets):
    if not bullets:
        return ""
    lines = []
    for b in bullets[:5]:
        lines.append(f"- [{b.topic}] {b.content}")
    return "\n".join(lines)


def _build_local_preprocess_context(session):
    rows = list(
        session.messages.exclude(role=Role.SYSTEM)
        .order_by("-created_at")
        .values_list("role", "content")[1:LOCAL_PREPROCESS_CONTEXT_MAX_MESSAGES + 1]
    )
    if not rows:
        return ""

    rows.reverse()
    role_name_map = {
        int(Role.USER): "User",
        int(Role.ASSISTANT): "Assistant",
    }
    lines = []
    for role, content in rows:
        normalized = (content or "").strip()
        if not normalized:
            continue
        speaker = role_name_map.get(int(role), "Other")
        lines.append(f"{speaker}: {normalized}")
    return "\n".join(lines)


def get_or_create_profile_for_user(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


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


def _semantic_memory_bullet_search(queryset, query, top_k=50):
    from app.services import embedding as embeddingService
    if not embeddingService.is_available():
        return None

    import numpy as np

    bullets = list(
        queryset.exclude(embedding_json="")
        .values_list("pk", "embedding_json")
    )
    if not bullets:
        return None

    queryEmbedding = embeddingService.encode_query(query)
    if queryEmbedding is None:
        return None

    corpus = []
    validPks = []
    for pk, embJson in bullets:
        vec = embeddingService.json_to_embedding(embJson)
        if vec is not None:
            corpus.append(vec)
            validPks.append(pk)

    if not corpus:
        return None

    corpusMatrix = np.array(corpus)
    ranked = embeddingService.cosine_search(queryEmbedding, corpusMatrix, top_k=top_k)

    orderedPks = [validPks[idx] for idx, score in ranked if score >= 0.25]
    if not orderedPks:
        return None

    from django.db.models import Case, When, IntegerField
    ordering = Case(
        *[When(pk=pk, then=pos) for pos, pk in enumerate(orderedPks)],
        output_field=IntegerField(),
    )
    return queryset.filter(pk__in=orderedPks).annotate(
        semantic_rank=ordering
    ).order_by("semantic_rank")


def _apply_memory_bullet_filters(queryset, q="", memory_type="", topic="", strength_min=""):
    normalized_q = (q or "").strip()
    normalized_memory_type = (memory_type or "").strip()
    normalized_topic = (topic or "").strip()
    normalized_strength_min = (strength_min or "").strip()

    if normalized_memory_type.isdigit():
        queryset = queryset.filter(memory_type=int(normalized_memory_type))
    if normalized_topic:
        queryset = queryset.filter(topic__icontains=normalized_topic)
    if normalized_strength_min.isdigit():
        queryset = queryset.filter(strength__gte=int(normalized_strength_min))

    if normalized_q:
        semantic_result = _semantic_memory_bullet_search(queryset, normalized_q)
        if semantic_result is not None:
            return semantic_result
        terms = [term for term in re.split(r"\s+", normalized_q) if term]
        for term in terms:
            queryset = queryset.filter(content__icontains=term)

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


DEFAULT_CHANNELS = ["General", "HR team"]
DEFAULT_PROJECTS = ["Project X", "Project Y", "Project Z"]


def ensure_default_groups_for_user(user):
    profile = get_or_create_profile_for_user(user)
    existing = set(
        Session.objects.filter(user=profile, is_group=True).values_list("title", flat=True)
    )
    for name in DEFAULT_CHANNELS + DEFAULT_PROJECTS:
        if name not in existing:
            Session.objects.create(user=profile, title=name, is_group=True)


def get_sidebar_sessions_for_user(user):
    ensure_default_groups_for_user(user)
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


def build_agent_reply_from_stream(content):
    trimmed = (content or "").strip()
    if not trimmed:
        return ""

    chunks = []

    try:
        for chunk in generate_reply_stream(trimmed):
            if chunk:
                chunks.append(chunk)
    except Exception:
        return FALLBACK_TEXT

    return "".join(chunks).strip() or FALLBACK_TEXT


def _should_use_local_model(prompt_text, classification):
    if classification != "simple":
        return False
    if not local_llm.is_available():
        return False
    token_limit = _safe_env_int("CHAT_LOCAL_MAX_TOKENS", 220)
    return len((prompt_text or "").split()) <= token_limit


def stream_user_message_with_agent_reply(session, content):
    trimmed = (content or "").strip()
    if not trimmed:
        raise ValueError("Message content is required.")
    started_at = time.monotonic()
    _stream_debug_log(f"start session_id={session.pk} prompt_len={len(trimmed)}")
    log_event("chat_stream_start", session_id=session.pk, prompt_len=len(trimmed))

    Message.objects.create(
        session=session,
        role=Role.USER,
        content=trimmed,
    )

    # TODO: Support multiple agent responses when multiple @mentions are used
    # Currently uses the first mentioned agent's system prompt for the response
    responding_agent = None
    try:
        from .agent_service import resolve_responding_agents
        agents = resolve_responding_agents(session.user.user, str(session.pk), trimmed)
        if agents:
            responding_agent = agents[0]
    except Exception:
        pass

    from concurrent.futures import ThreadPoolExecutor

    doc_chunks = []
    classification = "complex"

    def _classify():
        try:
            return gemini_classify(trimmed)
        except Exception:
            return regex_classify(trimmed)

    def _retrieve_docs():
        profile = session.user
        agent_id = responding_agent.get("id") if responding_agent else None
        return retrieve_relevant_document_chunks(profile, trimmed, agent_id=agent_id, top_k=5)

    try:
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_classify = executor.submit(_classify)
            future_docs = executor.submit(_retrieve_docs)
            classification = future_classify.result(timeout=10)
            doc_chunks = future_docs.result(timeout=15)
    except Exception:
        if classification == "complex":
            try:
                classification = _classify()
            except Exception:
                classification = "complex"

    log_event("chat_classify", session_id=session.pk, classification=classification)

    use_local = _should_use_local_model(trimmed, classification)

    try:
        if use_local:
            profile = get_or_create_profile_for_user(session.user.user)
            memory_obj, _ = Memory.get_or_create_for_profile(profile)
            bullets = memory_obj.retrieve_ranked_bullets(
                query=trimmed,
                learner_id=str(profile.user_id),
                context_scope_id=str(session.pk),
                top_k=10,
            )
            guidance = guidance_from_bullets(bullets)
            if doc_chunks:
                doc_text = "\n".join([f"[{c['filename']}]: {c['chunk']}" for c in doc_chunks[:3]])
                guidance = guidance + "\n\n[Relevant Documents]\n" + doc_text
            conversation_context = _build_local_preprocess_context(session)

            local_response = local_llm.generate_response(
                trimmed,
                guidance=guidance,
                conversation_context=conversation_context,
            )
            if local_response:
                log_event("chat_local_response_ok", session_id=session.pk, answer_len=len(local_response), bullets_retrieved=len(bullets))
                assistant_text = local_response
            else:
                ace_result = run_ace_chat_turn(session, trimmed, agent=responding_agent, doc_chunks=doc_chunks)
                assistant_text = (ace_result.get("answer") or "").strip() or FALLBACK_TEXT
        else:
            profile = get_or_create_profile_for_user(session.user.user)
            memory_obj, _ = Memory.get_or_create_for_profile(profile)
            bullets = memory_obj.retrieve_ranked_bullets(
                query=trimmed,
                learner_id=str(profile.user_id),
                context_scope_id=str(session.pk),
                top_k=10,
                min_learned=2,
                base_strength=100.0,
                relevance_w=0.60,
                strength_w=0.20,
                type_w=0.20,
                seed_penalty=0.25,
                learned_bonus=0.08,
            )
            guidance = _build_guidance_from_bullets(bullets)
            conversation_context = _build_conversation_context(session)

            system_prompt = ""
            if responding_agent:
                system_prompt = responding_agent.get("systemPrompt", "") if isinstance(responding_agent, dict) else getattr(responding_agent, "system_prompt", "")

            context_parts = []
            if system_prompt:
                context_parts.append(f"[System Instructions]\n{system_prompt}")
            if guidance:
                context_parts.append(f"[Relevant Knowledge]\n{guidance}")
            if doc_chunks:
                doc_text = "\n".join([f"From \"{c['filename']}\":\n  {c['chunk']}" for c in doc_chunks[:5]])
                context_parts.append(f"[Relevant Documents]\n{doc_text}")
            context_parts.append(f"[Recent Conversation]\n{conversation_context}")
            context_parts.append(f"[User Message]\n{trimmed}")
            full_prompt = "\n\n".join(context_parts)

            chunks_buf = []
            try:
                for chunk in generate_reply_stream(full_prompt):
                    if chunk:
                        chunks_buf.append(chunk)
            except Exception:
                pass
            assistant_text = "".join(chunks_buf).strip() or FALLBACK_TEXT

        log_event(
            "chat_stream_ace_ok",
            session_id=session.pk,
            answer_len=len(assistant_text),
            pipeline="local_qwen" if use_local else "gemini_direct",
            agent_name=responding_agent.get("name") if responding_agent else None,
        )
        _stream_debug_log(
            "ace_ok "
            f"session_id={session.pk} answer_len={len(assistant_text)} "
            f"pipeline={'local_qwen' if use_local else 'gemini_direct'} "
            f"elapsed_ms={int((time.monotonic() - started_at) * 1000)}"
        )
    except Exception as exc:
        assistant_text = FALLBACK_TEXT
        log_event(
            "chat_stream_ace_failed_fallback",
            session_id=session.pk,
            error_type=exc.__class__.__name__,
            answer_len=len(assistant_text),
        )
        _stream_debug_log(
            "ace_failed_fallback "
            f"session_id={session.pk} answer_len={len(assistant_text)} "
            f"elapsed_ms={int((time.monotonic() - started_at) * 1000)}"
        )

    if not assistant_text:
        assistant_text = FALLBACK_TEXT

    chunks = []
    delta_count = 0
    if assistant_text == FALLBACK_TEXT:
        chunk_queue = [assistant_text]
    elif len(assistant_text) <= INITIAL_STREAM_CHUNK_SIZE:
        chunk_queue = [assistant_text]
    else:
        chunk_queue = [
            assistant_text[:INITIAL_STREAM_CHUNK_SIZE],
            assistant_text[INITIAL_STREAM_CHUNK_SIZE:],
        ]

    for chunk in chunk_queue:
        if chunk:
            chunks.append(chunk)
            delta_count += 1
            if delta_count <= 3:
                _stream_debug_log(
                    "delta "
                    f"session_id={session.pk} index={delta_count} chunk_len={len(chunk)} "
                    f"total_len={len(''.join(chunks))}"
                )
            yield {
                "type": "delta",
                "content": chunk,
                "html": str(render_assistant_markdown_html("".join(chunks))),
            }

    if not chunks:
        chunks.append(FALLBACK_TEXT)
        assistant_text = FALLBACK_TEXT
        _stream_debug_log(f"empty_answer_fallback session_id={session.pk}")
        yield {
            "type": "delta",
            "content": FALLBACK_TEXT,
            "html": str(render_assistant_markdown_html(FALLBACK_TEXT)),
        }

    sender_agent_orm = None
    if responding_agent:
        try:
            from .models.agent import Agent
            sender_agent_orm = Agent.objects.filter(name=responding_agent.get("name", "")).first()
        except Exception:
            pass

    assistant_message = Message.objects.create(
        session=session,
        role=Role.ASSISTANT,
        content=assistant_text,
        sender_agent=sender_agent_orm,
    )
    session.updated_at = timezone.now()
    session.save(update_fields=["updated_at"])

    donePayload = {
        "type": "done",
        "message_id": assistant_message.id,
        "content": assistant_text,
        "html": str(render_assistant_markdown_html(assistant_text)),
    }
    if responding_agent:
        donePayload["agentName"] = responding_agent.get("name", "")
        donePayload["agentId"] = responding_agent.get("id", "")

    yield donePayload

    try:
        from app.services import pusher_service
        pusher_service.send_message(session.pk, {
            "messageId": assistant_message.id,
            "content": assistant_text,
            "html": str(render_assistant_markdown_html(assistant_text)),
            "role": "assistant",
            "agentName": responding_agent.get("name", "") if responding_agent else None,
            "agentId": responding_agent.get("id", "") if responding_agent else None,
        })
    except Exception:
        pass
    log_event(
        "chat_stream_done",
        session_id=session.pk,
        message_id=assistant_message.id,
        answer_len=len(assistant_text),
        elapsed_ms=int((time.monotonic() - started_at) * 1000),
    )
    _stream_debug_log(
        "done "
        f"session_id={session.pk} message_id={assistant_message.id} "
        f"delta_count={delta_count or 1} answer_len={len(assistant_text)} "
        f"elapsed_ms={int((time.monotonic() - started_at) * 1000)}"
    )

    try:
        ace_result = run_ace_chat_turn(session, trimmed, agent=responding_agent, doc_chunks=doc_chunks)
        log_event(
            "chat_post_response_memory",
            session_id=session.pk,
            ace_delta=ace_result.get("ace_delta"),
        )
    except Exception:
        pass


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
    return get_analytics_dashboard_context_with_reports(user)


def get_analytics_dashboard_context_with_reports(user, session_group="month", memory_group="memory_type"):
    metrics = _get_analytics_metrics_for_user(user)
    profile = get_or_create_profile_for_user(user)
    type_choices = dict(MemoryBullet._meta.get_field("memory_type").choices)
    type_summary = [
        {"label": type_choices.get(d["memory_type"], str(d["memory_type"])), "count": d["count"]}
        for d in metrics["type_distribution_raw"]
    ]

    session_group = (session_group or "month").strip().lower()
    if session_group not in {"day", "week", "month"}:
        session_group = "month"

    session_group_field = {
        "day": TruncDate("created_at"),
        "week": TruncWeek("created_at"),
        "month": TruncMonth("created_at"),
    }[session_group]

    grouped_sessions = (
        Session.objects
        .filter(user=profile)
        .annotate(group_value=session_group_field)
        .values("group_value")
        .annotate(
            session_count=Count("id",distinct=True),
            message_count=Count("messages__id",distinct=True),
        )
        .order_by("-group_value")
    )
    session_grouped_rows = []
    for row in grouped_sessions:
        group_date = row["group_value"]
        if session_group == "day":
            group_label = group_date.strftime("%Y-%m-%d")
        elif session_group == "week":
            group_label = f"Week of {group_date.strftime('%Y-%m-%d')}"
        else:
            group_label = group_date.strftime("%Y-%m")
        session_grouped_rows.append(
            {
                "group_label": group_label,
                "session_count": row["session_count"],
                "message_count": row["message_count"],
            }
        )

    memory_group = (memory_group or "memory_type").strip().lower()
    if memory_group not in {"memory_type", "topic", "month"}:
        memory_group = "memory_type"

    base_bullets = MemoryBullet.objects.filter(memory__user=profile)
    if memory_group == "memory_type":
        grouped_bullets = (
            base_bullets
            .values("memory_type")
            .annotate(
                bullet_count=Count("id"),
                avg_strength=Avg("strength"),
            )
            .order_by("memory_type")
        )
        memory_grouped_rows = [
            {
                "group_label": type_choices.get(row["memory_type"], str(row["memory_type"])),
                "bullet_count": row["bullet_count"],
                "avg_strength": row["avg_strength"],
            }
            for row in grouped_bullets
        ]
    elif memory_group == "topic":
        grouped_bullets = (
            base_bullets
            .values("topic")
            .annotate(
                bullet_count=Count("id"),
                avg_strength=Avg("strength"),
            )
            .order_by("topic")
        )
        memory_grouped_rows = [
            {
                "group_label": row["topic"] or "(No Topic)",
                "bullet_count": row["bullet_count"],
                "avg_strength": row["avg_strength"],
            }
            for row in grouped_bullets
        ]
    else:
        grouped_bullets = (
            base_bullets
            .annotate(group_value=TruncMonth("created_at"))
            .values("group_value")
            .annotate(
                bullet_count=Count("id"),
                avg_strength=Avg("strength"),
            )
            .order_by("-group_value")
        )
        memory_grouped_rows = [
            {
                "group_label": row["group_value"].strftime("%Y-%m"),
                "bullet_count": row["bullet_count"],
                "avg_strength": row["avg_strength"],
            }
            for row in grouped_bullets
        ]

    return {
        "total_memories": metrics["total_memories"],
        "total_sessions": metrics["total_sessions"],
        "total_messages": metrics["total_messages"],
        "avg_strength": metrics["avg_strength"],
        "type_summary": type_summary,
        "session_group": session_group,
        "memory_group": memory_group,
        "session_grouped_rows": session_grouped_rows,
        "memory_grouped_rows": memory_grouped_rows,
        "session_group_count": len(session_grouped_rows),
        "memory_group_count": len(memory_grouped_rows),
    }


def get_session_report_export_rows(user, q=""):
    profile = get_or_create_profile_for_user(user)
    normalized_q = (q or "").strip()
    sessions_qs = (
        Session.objects
        .filter(user=profile)
        .annotate(message_count=Count("messages"))
        .order_by("-created_at")
    )
    if normalized_q:
        sessions_qs = sessions_qs.filter(title__icontains=normalized_q)

    return [
        {
            "title": s.title,
            "created_at": s.created_at.isoformat(),
            "message_count": s.message_count,
        }
        for s in sessions_qs
    ]


def get_memory_bullet_report_export_rows(user, q=""):
    profile = get_or_create_profile_for_user(user)
    normalized_q = (q or "").strip()
    bullets_qs = (
        MemoryBullet.objects
        .filter(memory__user=profile)
        .order_by("-created_at")
    )
    if normalized_q:
        bullets_qs = bullets_qs.filter(content__icontains=normalized_q)

    return [
        {
            "content": b.content,
            "memory_type": b.get_memory_type_display(),
            "created_at": b.created_at.isoformat(),
        }
        for b in bullets_qs
    ]


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


def get_api_daily_active_users_payload():
    daily = list(
        Message.objects
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(
            active_users=Count("session__user_id", distinct=True),
            message_count=Count("id"),
        )
        .order_by("day")
    )

    if not daily:
        return {"count": 0, "results": []}

    daily_map = {
        row["day"]: {
            "active_users": row["active_users"],
            "message_count": row["message_count"],
        }
        for row in daily
    }

    current_day = min(daily_map.keys())
    end_day = max(daily_map.keys())
    results = []

    while current_day <= end_day:
        point = daily_map.get(current_day, {"active_users": 0, "message_count": 0})
        results.append(
            {
                "date": current_day.isoformat(),
                "active_users": point["active_users"],
                "message_count": point["message_count"],
            }
        )
        current_day += timedelta(days=1)

    return {"count": len(results), "results": results}
