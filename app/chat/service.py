import io
import json
import os
import re
import time
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from django.http import Http404
from django.utils import timezone

import math

from memoria.event_log import log_event
from app.services.gemini import generate_reply_stream, classify_prompt as gemini_classify
from app.services.classifier import classify_prompt as regex_classify
from app.services import local_llm
from app.services import neo4j_memory as neo4j
from .ace_runtime import run_ace_chat_turn, guidance_from_bullets, _build_recent_conversation_context
from .rendering import render_assistant_markdown_html, normalize_mentions
from .models import Memory
from .models.message import Role
from .utils import safe_env_bool, safe_env_int, get_or_create_profile

PROGRESSIVE_COLORS = ["#575BEF", "#6F82FF", "#8DA0FF", "#AEBBFF", "#D6DDFF"]
SEGMENT_COLORS = ["#9698FF", "#664FA1", "#FFC5D6", "#DAC6FF", "#B4EDE4"]
CHART_BG = "#F7F8FF"
CHART_GRID = "#DCE1FF"
CHART_TEXT = "#2F3A4A"
CHART_MUTED = "#6A7290"
LOCAL_PREPROCESS_CONTEXT_MAX_MESSAGES = 6
INITIAL_STREAM_CHUNK_SIZE = 5
FALLBACK_TEXT = "Sorry, I couldn't reach the AI service just now."
MEMORY_TYPE_LABELS = {1: "Semantic", 2: "Episodic", 3: "Procedural"}


def _session_id(session):
    if isinstance(session, dict):
        return str(session.get("id", ""))
    return str(session.pk)

MODEL_PRICING = {
    "gemini-3-flash-preview": {"input_per_1m": 0.15, "output_per_1m": 0.60},
    "gemini-3.1-flash-lite-preview": {"input_per_1m": 0.075, "output_per_1m": 0.30},
    "qwen3.5-0.8b": {"input_per_1m": 0.0, "output_per_1m": 0.0},
}


def _estimate_cost(model_name, prompt_tokens, completion_tokens):
    rates = MODEL_PRICING.get(model_name, {"input_per_1m": 0.0, "output_per_1m": 0.0})
    return (prompt_tokens * rates["input_per_1m"] + completion_tokens * rates["output_per_1m"]) / 1_000_000


def retrieve_relevant_document_chunks(user_profile, query, agent_id=None, top_k=5):
    try:
        from app.services import embedding as embedding_service
        if not embedding_service.is_available():
            return []
    except Exception:
        return []

    profileId = str(user_profile.pk) if hasattr(user_profile, "pk") else str(user_profile)
    docs = neo4j.get_documents_for_user(profileId, agent_id=str(agent_id) if agent_id else None)
    if not docs:
        return []

    allChunks = []
    for doc in docs:
        rawText = doc.get("rawText", "") or ""
        if len(rawText.strip()) < 20:
            continue
        parsedFields = doc.get("parsedFields", "{}")
        if isinstance(parsedFields, str):
            try:
                parsedFields = json.loads(parsedFields)
            except (json.JSONDecodeError, TypeError):
                parsedFields = {}
        cached = parsedFields.get("chunk_embeddings") if isinstance(parsedFields, dict) else None
        filename = doc.get("filename", "")
        if cached:
            for item in cached:
                allChunks.append({"filename": filename, "text": item["text"], "embedding": item["embedding"]})
        else:
            chunkSize = 500
            overlap = 50
            chunks = []
            for i in range(0, len(rawText), chunkSize - overlap):
                chunk = rawText[i:i + chunkSize].strip()
                if len(chunk) > 20:
                    chunks.append(chunk)
            if chunks:
                try:
                    embeddings = embedding_service.encode_texts(chunks)
                    for idx, chunk in enumerate(chunks):
                        allChunks.append({"filename": filename, "text": chunk, "embedding": embeddings[idx].tolist()})
                except Exception:
                    for chunk in chunks:
                        allChunks.append({"filename": filename, "text": chunk, "embedding": None})

    if not allChunks:
        return []

    try:
        import numpy as np
        queryEmb = embedding_service.encode_query(query)
        validChunks = [c for c in allChunks if c["embedding"] is not None]
        if not validChunks:
            return []
        corpus = np.array([c["embedding"] for c in validChunks])
        results = embedding_service.cosine_search(queryEmb, corpus, top_k=top_k)
        return [{"filename": validChunks[idx]["filename"], "chunk": validChunks[idx]["text"], "similarity": float(score)} for idx, score in results if score > 0.2]
    except Exception:
        return []


def _is_stream_debug_enabled():
    return (os.getenv("CHAT_STREAM_DEBUG", "0") or "").strip().lower() in {"1", "true", "yes", "on"}


def _stream_debug_log(message):
    if _is_stream_debug_enabled():
        log_event("chat_stream_debug", message=message)


_build_conversation_context = _build_recent_conversation_context
_build_guidance_from_bullets = guidance_from_bullets


def _build_local_preprocess_context(session):
    sessionId = _session_id(session)
    rows = neo4j.get_messages_for_session_values(
        sessionId,
        exclude_role=int(Role.SYSTEM),
        limit=LOCAL_PREPROCESS_CONTEXT_MAX_MESSAGES + 1,
    )
    if not rows:
        return ""

    rows = rows[1:LOCAL_PREPROCESS_CONTEXT_MAX_MESSAGES + 1]
    rows.reverse()
    roleNameMap = {
        "user": "User",
        "assistant": "Assistant",
        str(int(Role.USER)): "User",
        str(int(Role.ASSISTANT)): "Assistant",
        int(Role.USER): "User",
        int(Role.ASSISTANT): "Assistant",
    }
    lines = []
    for row in rows:
        normalized = (row.get("content", "") or "").strip()
        if not normalized:
            continue
        role = row.get("role", "")
        speaker = roleNameMap.get(role, roleNameMap.get(str(role), "Other"))
        lines.append(f"{speaker}: {normalized}")
    return "\n".join(lines)


def get_or_create_profile_for_user(user):
    return get_or_create_profile(user)


def _get_session_queryset_for_user(user):
    profile = get_or_create_profile_for_user(user)
    return neo4j.get_sessions_for_user(str(profile.pk))


def _get_session_or_404_for_user(user, session_id, with_messages=False):
    profile = get_or_create_profile_for_user(user)
    session = neo4j.get_session(str(profile.pk), str(session_id))
    if session is None:
        raise Http404
    if with_messages:
        session["messages"] = neo4j.get_messages_for_session(str(session_id))
    return session


def _get_memory_bullets_for_user(user):
    profile = get_or_create_profile_for_user(user)
    memoryData = neo4j.get_or_create_memory(str(profile.pk))
    memoryId = memoryData.get("id", "")
    if not memoryId:
        return []
    return neo4j.get_bullets_for_memory(memoryId, learner_id=str(profile.user_id))


def _apply_memory_bullet_filters(bullets, q="", memory_type="", topic="", strength_min=""):
    normalizedQ = (q or "").strip()
    normalizedMemoryType = (memory_type or "").strip()
    normalizedTopic = (topic or "").strip()
    normalizedStrengthMin = (strength_min or "").strip()

    if normalizedMemoryType.isdigit():
        targetType = int(normalizedMemoryType)
        bullets = [b for b in bullets if b.get("memoryType") == targetType]
    if normalizedTopic:
        lowerTopic = normalizedTopic.lower()
        bullets = [b for b in bullets if lowerTopic in (b.get("topic", "") or "").lower()]
    if normalizedStrengthMin.isdigit():
        minVal = int(normalizedStrengthMin)
        bullets = [b for b in bullets if (b.get("strength", 0) or 0) >= minVal]
    if normalizedQ:
        terms = [term.lower() for term in re.split(r"\s+", normalizedQ) if term]
        for term in terms:
            bullets = [b for b in bullets if term in (b.get("content", "") or "").lower()]

    return bullets


def get_sidebar_sessions_for_user(user):
    return _get_session_queryset_for_user(user)


def get_home_context_for_user(user):
    profile = get_or_create_profile_for_user(user)
    profileId = str(profile.pk)
    sessions = neo4j.get_sessions_for_user(profileId)
    return {
        "username": user.username,
        "sessions": sessions,
        "memories": [],
    }


def create_home_session_for_user(user, content):
    profile = get_or_create_profile_for_user(user)
    profileId = str(profile.pk)
    trimmed = (content or "").strip()
    title = trimmed[:80] if trimmed else "New conversation"
    sessionData = neo4j.create_session(profileId, title)
    sessionId = sessionData.get("id", "")
    if sessionId and trimmed:
        neo4j.create_message(
            session_id=sessionId,
            content=trimmed,
            created_by=profileId,
            role="user",
        )
    return sessionData


def get_session_for_user(user, session_id, with_messages=False):
    return _get_session_or_404_for_user(user, session_id, with_messages=with_messages)


def get_session_for_user_or_member(user, session_id, with_messages=False, require_admin=False):
    try:
        return _get_session_or_404_for_user(user, session_id, with_messages=with_messages)
    except Http404:
        profile = get_or_create_profile_for_user(user)
        profileId = str(profile.pk)
        members = neo4j.get_members_for_session(str(session_id))
        isMember = False
        for m in members:
            if str(m.get("userId", "")) == profileId:
                if require_admin and m.get("role") != "admin":
                    continue
                isMember = True
                break
        if not isMember:
            raise Http404
        session = neo4j.get_session(profileId, str(session_id))
        if session is None:
            for m in members:
                foundSession = neo4j.get_session(str(m.get("userId", "")), str(session_id))
                if foundSession is not None:
                    session = foundSession
                    break
        if session is None:
            raise Http404
        if with_messages:
            session["messages"] = neo4j.get_messages_for_session(str(session_id))
        return session


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


_local_model_preload_attempted = False


def _should_use_local_model(prompt_text, classification):
    if safe_env_bool("CHAT_PREFER_LOCAL_LLM", False) and local_llm.is_available():
        return True
    gemini_key = getattr(__import__("django.conf", fromlist=["settings"]).settings, "GEMINI_API_KEY", "") or ""
    if not gemini_key.strip() and local_llm.is_available():
        return True
    if not safe_env_bool("CHAT_LOCAL_MODEL_ENABLED", False):
        return False
    if classification != "simple":
        return False
    if local_llm.is_loaded():
        token_limit = safe_env_int("CHAT_LOCAL_MAX_TOKENS", 220)
        return len((prompt_text or "").split()) <= token_limit
    return False


def _preload_local_model():
    try:
        local_llm.generate_response("warmup")
    except Exception:
        pass


def _startup_preload():
    global _local_model_preload_attempted
    if _local_model_preload_attempted:
        return
    if not safe_env_bool("CHAT_LOCAL_MODEL_ENABLED", False):
        return
    if not local_llm.is_available():
        return
    _local_model_preload_attempted = True
    import threading
    threading.Thread(target=_preload_local_model, daemon=True).start()


_startup_preload()


# ---------------------------------------------------------------------------
# Background generation pool
#
# The agent's full response generation (Gemini call + DB writes + streaming)
# used to run on the HTTP request thread. This coupled the generation lifecycle
# to the client's network state: if the user navigated away while the agent was
# "thinking", the request thread still held the session lock until the browser
# finally disconnected, and any pending deltas the client had not yet received
# were lost. Moving the work into a shared thread pool lets the request thread
# read from a queue and stream whatever has been produced so far, while the
# background worker continues until the response is fully persisted regardless
# of the client's connection state.
# ---------------------------------------------------------------------------

import asyncio as _asyncio
import threading as _threading
import uuid as _uuid
from concurrent.futures import ThreadPoolExecutor as _ThreadPoolExecutor
from queue import Queue as _Queue, Empty as _QueueEmpty


_GENERATION_POOL: _ThreadPoolExecutor | None = None
_GENERATION_STATE_LOCK = _threading.Lock()
_BROADCAST_QUEUE_MAXSIZE = 256

# Unique per-process identifier. Used to tag in-flight generations so a
# client that reconnects on a *different* worker can tell it has landed on
# the wrong process and gracefully fall back to polling rather than
# silently getting an empty stream. For single-worker deploys this is a
# debugging aid; for multi-worker deploys the operator should enable
# sticky sessions at the load-balancer layer (e.g. Render's
# `stickySessionsEnabled: true`).
INSTANCE_ID = f"{_uuid.uuid4().hex[:12]}"


class _GenerationBroadcast:
    """Fan-out buffer for an in-flight generation.

    Every subscriber receives the full history of payloads already produced,
    followed by any new payloads the background worker emits. A trailing
    ``None`` terminates each subscriber's queue so the HTTP stream closes
    cleanly. Late subscribers (e.g. a user navigating back to the conversation
    mid-generation) see exactly the same payload sequence as the original
    caller.

    Supports both sync subscribers (``queue.Queue``, for thread-based
    consumers) and async subscribers (``asyncio.Queue``, for async views under
    ASGI). Queues are bounded; if a slow subscriber falls behind, the oldest
    payload is dropped to protect the worker from unbounded memory growth.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._buffer: list = []
        self._sync_subs: list[_Queue] = []
        self._async_subs: list[tuple[_asyncio.Queue, _asyncio.AbstractEventLoop]] = []
        self._closed = False
        self._lock = _threading.Lock()

    def publish(self, payload):
        with self._lock:
            self._buffer.append(payload)
            sync_targets = list(self._sync_subs)
            async_targets = list(self._async_subs)
        for q in sync_targets:
            self._safe_put_sync(q, payload)
        for q, loop in async_targets:
            self._safe_put_async(q, loop, payload)

    def close(self):
        with self._lock:
            self._closed = True
            sync_targets = list(self._sync_subs)
            async_targets = list(self._async_subs)
            self._sync_subs.clear()
            self._async_subs.clear()
        for q in sync_targets:
            self._safe_put_sync(q, None)
        for q, loop in async_targets:
            self._safe_put_async(q, loop, None)

    @staticmethod
    def _safe_put_sync(q: _Queue, payload):
        try:
            q.put_nowait(payload)
        except Exception:
            try:
                q.get_nowait()
                q.put_nowait(payload)
            except Exception:
                pass

    @staticmethod
    def _safe_put_async(q: _asyncio.Queue, loop: _asyncio.AbstractEventLoop, payload):
        def _apply():
            try:
                q.put_nowait(payload)
            except _asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except Exception:
                    pass
        try:
            loop.call_soon_threadsafe(_apply)
        except Exception:
            pass

    def subscribe(self) -> _Queue:
        q: _Queue = _Queue(maxsize=_BROADCAST_QUEUE_MAXSIZE)
        with self._lock:
            for past in self._buffer:
                self._safe_put_sync(q, past)
            if self._closed:
                self._safe_put_sync(q, None)
            else:
                self._sync_subs.append(q)
        return q

    def subscribe_async(self, loop: _asyncio.AbstractEventLoop) -> _asyncio.Queue:
        q: _asyncio.Queue = _asyncio.Queue(maxsize=_BROADCAST_QUEUE_MAXSIZE)
        with self._lock:
            for past in self._buffer:
                try:
                    q.put_nowait(past)
                except _asyncio.QueueFull:
                    break
            if self._closed:
                try:
                    q.put_nowait(None)
                except _asyncio.QueueFull:
                    pass
            else:
                self._async_subs.append((q, loop))
        return q

    def has_any_history(self) -> bool:
        with self._lock:
            return bool(self._buffer)


_ACTIVE_GENERATIONS: dict[str, _GenerationBroadcast] = {}


def _get_generation_pool() -> _ThreadPoolExecutor:
    global _GENERATION_POOL
    if _GENERATION_POOL is None:
        with _GENERATION_STATE_LOCK:
            if _GENERATION_POOL is None:
                max_workers = safe_env_int("CHAT_GENERATION_POOL_SIZE", 8)
                _GENERATION_POOL = _ThreadPoolExecutor(
                    max_workers=max(2, max_workers),
                    thread_name_prefix="agent-gen",
                )
    return _GENERATION_POOL


_PREPROCESS_POOL: _ThreadPoolExecutor | None = None
_PREPROCESS_POOL_LOCK = _threading.Lock()


def _get_preprocess_pool() -> _ThreadPoolExecutor:
    """Shared pool for short-lived preprocessing tasks inside a generation run
    (prompt classification, document retrieval). A module-level pool avoids the
    per-request create/destroy churn of building a fresh ``ThreadPoolExecutor``
    for every chat message."""
    global _PREPROCESS_POOL
    if _PREPROCESS_POOL is None:
        with _PREPROCESS_POOL_LOCK:
            if _PREPROCESS_POOL is None:
                max_workers = safe_env_int("CHAT_PREPROCESS_POOL_SIZE", 8)
                _PREPROCESS_POOL = _ThreadPoolExecutor(
                    max_workers=max(2, max_workers),
                    thread_name_prefix="chat-pre",
                )
    return _PREPROCESS_POOL


def start_background_generation(session, content, *, skip_user_message=False) -> _Queue:
    """Run the full generation pipeline in the background thread pool.

    Returns a ``Queue`` subscribed to the in-flight broadcast. The caller drains
    the queue and forwards payloads to the HTTP client. If the client
    disconnects, the queue is garbage-collected but the background worker keeps
    running, so the assistant message is persisted and the session generation
    lock is released only when the work truly finishes. Concurrent subscribers
    (e.g. the initial POST response plus a reconnecting GET) each receive the
    full payload sequence.
    """
    session_id = _session_id(session)

    with _GENERATION_STATE_LOCK:
        existing = _ACTIVE_GENERATIONS.get(session_id)
        if existing is not None:
            return existing.subscribe()
        broadcast = _GenerationBroadcast(session_id)
        _ACTIVE_GENERATIONS[session_id] = broadcast

    subscriber_queue = broadcast.subscribe()

    def _run():
        try:
            for payload in stream_user_message_with_agent_reply(
                session, content, skip_user_message=skip_user_message,
            ):
                broadcast.publish(payload)
        except Exception as exc:
            log_event(
                "chat_background_generation_failed",
                session_id=session_id,
                error=str(exc),
            )
            broadcast.publish({"type": "error", "error": str(exc)})
        finally:
            broadcast.close()
            with _GENERATION_STATE_LOCK:
                _ACTIVE_GENERATIONS.pop(session_id, None)
            try:
                neo4j.release_session_generation_lock(session_id)
            except Exception as exc:
                log_event(
                    "chat_background_generation_lock_release_failed",
                    session_id=session_id,
                    error=str(exc),
                )
            try:
                from django.db import connections
                connections.close_all()
            except Exception:
                pass

    _get_generation_pool().submit(_run)
    return subscriber_queue


def subscribe_to_active_generation(session_id: str) -> _Queue | None:
    """Return a fresh subscriber queue for an in-flight generation, or ``None``
    if no generation is running for this session. Used when a client reconnects
    to a conversation mid-generation."""
    with _GENERATION_STATE_LOCK:
        broadcast = _ACTIVE_GENERATIONS.get(session_id)
    if broadcast is None:
        return None
    return broadcast.subscribe()


async def start_background_generation_async(
    session, content, *, skip_user_message=False
) -> _asyncio.Queue:
    """Async-aware variant of :func:`start_background_generation`.

    Returns an ``asyncio.Queue`` bound to the current event loop. The
    background worker still runs in the sync thread pool, but publishes
    payloads onto the loop via ``call_soon_threadsafe``. Stopping iteration
    early (client disconnect in an async view) does NOT stop the worker."""
    session_id = _session_id(session)
    loop = _asyncio.get_running_loop()

    with _GENERATION_STATE_LOCK:
        existing = _ACTIVE_GENERATIONS.get(session_id)
        if existing is not None:
            return existing.subscribe_async(loop)
        broadcast = _GenerationBroadcast(session_id)
        _ACTIVE_GENERATIONS[session_id] = broadcast

    log_event(
        "chat_generation_started",
        session_id=session_id,
        instance_id=INSTANCE_ID,
    )

    subscriber_queue = broadcast.subscribe_async(loop)

    def _run():
        try:
            for payload in stream_user_message_with_agent_reply(
                session, content, skip_user_message=skip_user_message,
            ):
                broadcast.publish(payload)
        except Exception as exc:
            log_event(
                "chat_background_generation_failed",
                session_id=session_id,
                error=str(exc),
            )
            broadcast.publish({"type": "error", "error": str(exc)})
        finally:
            broadcast.close()
            with _GENERATION_STATE_LOCK:
                _ACTIVE_GENERATIONS.pop(session_id, None)
            try:
                neo4j.release_session_generation_lock(session_id)
            except Exception as exc:
                log_event(
                    "chat_background_generation_lock_release_failed",
                    session_id=session_id,
                    error=str(exc),
                )
            try:
                from django.db import connections
                connections.close_all()
            except Exception:
                pass

    _get_generation_pool().submit(_run)
    return subscriber_queue


def subscribe_to_active_generation_async(
    session_id: str,
) -> _asyncio.Queue | None:
    """Async-aware variant of :func:`subscribe_to_active_generation`. Must be
    called from within a running event loop."""
    loop = _asyncio.get_running_loop()
    with _GENERATION_STATE_LOCK:
        broadcast = _ACTIVE_GENERATIONS.get(session_id)
    if broadcast is None:
        # Nothing to join on this worker. If a generation is in fact running
        # on a sibling worker (multi-worker deploys without sticky sessions),
        # the client will degrade to ``waitForUnlock`` polling and reload —
        # but we log the mismatch so operators can spot it in telemetry.
        if neo4j.ensure_generation_lock_fresh(session_id):
            log_event(
                "chat_subscribe_cross_worker_miss",
                session_id=session_id,
                instance_id=INSTANCE_ID,
            )
        return None
    return broadcast.subscribe_async(loop)


async def stream_queue_payloads_async(
    queue: _asyncio.Queue,
    *,
    idle_timeout: int = 120,
    heartbeat_interval: int = 15,
):
    """Async counterpart of :func:`stream_queue_payloads`. Yields payloads
    from an asyncio-Queue subscriber until the sentinel arrives, emitting a
    heartbeat every ``heartbeat_interval`` seconds so intermediate proxies do
    not drop the connection."""
    last_real_payload = time.monotonic()
    while True:
        try:
            payload = await _asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
        except _asyncio.TimeoutError:
            if time.monotonic() - last_real_payload >= idle_timeout:
                return
            yield {"type": "heartbeat", "ts": time.time()}
            continue
        if payload is None:
            return
        last_real_payload = time.monotonic()
        yield payload


def stream_queue_payloads(
    queue: _Queue,
    *,
    idle_timeout: int = 120,
    heartbeat_interval: int = 15,
):
    """Yield payloads from a broadcast subscriber queue until the sentinel
    ``None`` arrives or no payload appears for ``idle_timeout`` seconds.
    Emits a ``heartbeat`` payload every ``heartbeat_interval`` seconds so
    intermediate proxies do not drop the connection while the upstream model
    is still thinking. Stopping iteration early (client disconnect) does NOT
    stop the background worker — it just drops this subscriber."""
    last_real_payload = time.monotonic()
    while True:
        try:
            payload = queue.get(timeout=heartbeat_interval)
        except _QueueEmpty:
            if time.monotonic() - last_real_payload >= idle_timeout:
                return
            yield {"type": "heartbeat", "ts": time.time()}
            continue
        if payload is None:
            return
        last_real_payload = time.monotonic()
        yield payload


def stream_user_message_with_agent_reply(session, content, *, skip_user_message=False):
    trimmed = (content or "").strip()
    if not trimmed:
        raise ValueError("Message content is required.")
    started_at = time.monotonic()
    sessionId = _session_id(session)
    _stream_debug_log(f"start session_id={sessionId} prompt_len={len(trimmed)}")
    log_event("chat_stream_start", session_id=sessionId, prompt_len=len(trimmed))

    sessionUser = session.get("_user") if isinstance(session, dict) else session.user.user
    sessionProfileId = session.get("_profile_id") if isinstance(session, dict) else str(session.user.pk)

    try:
        userProfile = get_or_create_profile_for_user(sessionUser)
        userDisplayName = getattr(userProfile, "display_name", "") or getattr(sessionUser, "username", "") or "User"
    except Exception:
        userDisplayName = "User"
    userDisplayNameCleaned = re.sub(r"\s*\([^)]*\)", "", userDisplayName).strip() or userDisplayName
    userHandle = re.sub(r"[\s'\-]+", "", userDisplayNameCleaned) or "User"
    userUsername = (getattr(sessionUser, "username", "") or "").strip()

    userMentionCandidates = set()
    for candidate in (userHandle, userUsername, userDisplayNameCleaned, userDisplayName):
        if candidate:
            userMentionCandidates.add(candidate.replace("'", "").replace(" ", "").lower())
    for part in re.split(r"[\s'\-()]+", userDisplayName):
        if part and len(part) >= 2:
            userMentionCandidates.add(part.lower())

    def _substitute_user_placeholder(text):
        if not text:
            return text
        if userHandle and userHandle != "User":
            text = re.sub(r"(?<!\w)@User(?!\w)", f"@{userHandle}", text)
        return text

    def _reply_mentions_user(text):
        from .agent_service import parse_agent_mentions
        if not text:
            return False
        for tok in parse_agent_mentions(text):
            tokCompact = tok.replace("'", "").replace(" ", "").lower()
            if tokCompact and tokCompact in userMentionCandidates:
                return True
        return False

    if not skip_user_message:
        neo4j.create_message(
            session_id=sessionId,
            content=trimmed,
            created_by=sessionProfileId,
            role="user",
        )

    responding_agent = None
    try:
        from .agent_service import resolve_responding_agents
        agents = resolve_responding_agents(sessionUser, sessionId, trimmed)
        if agents:
            responding_agent = agents[0]
    except Exception:
        pass

    doc_chunks = []
    classification = "complex"

    def _classify():
        try:
            return gemini_classify(trimmed)
        except Exception:
            return regex_classify(trimmed)

    def _retrieve_docs():
        agentId = responding_agent.get("id") if responding_agent else None
        return retrieve_relevant_document_chunks(sessionProfileId, trimmed, agent_id=agentId, top_k=5)

    _pool = _get_preprocess_pool()
    future_classify = _pool.submit(_classify)
    future_docs = _pool.submit(_retrieve_docs)
    try:
        classification = future_classify.result(timeout=10)
    except Exception:
        try:
            classification = _classify()
        except Exception:
            classification = "complex"
    try:
        doc_chunks = future_docs.result(timeout=15)
    except Exception:
        doc_chunks = []

    log_event("chat_classify", session_id=sessionId, classification=classification)
    try:
        neo4j.create_request_log(
            user_id=sessionProfileId,
            session_id=sessionId,
            request_type="classify",
            model_name="gemini-3.1-flash-lite-preview",
            pipeline="classifier",
            status="success",
            latency_ms=0,
        )
    except Exception:
        pass

    use_local = _should_use_local_model(trimmed, classification)
    usage_metadata = None
    chunks_buf: list = []
    delta_idx = 0

    try:
        if use_local:
            profile = get_or_create_profile_for_user(sessionUser)
            memory_obj, _ = Memory.get_or_create_for_profile(profile)
            bullets = memory_obj.retrieve_ranked_bullets(
                query=trimmed,
                learner_id=str(profile.user_id),
                context_scope_id=sessionId,
                top_k=10,
                min_learned=2,
                base_strength=100.0,
                relevance_w=0.60,
                strength_w=0.20,
                type_w=0.20,
                seed_penalty=0.25,
                learned_bonus=0.08,
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
                log_event("chat_local_response_ok", session_id=sessionId, answer_len=len(local_response), bullets_retrieved=len(bullets))
                assistant_text = local_response
            else:
                ace_result = run_ace_chat_turn(session, trimmed, agent=responding_agent, doc_chunks=doc_chunks)
                assistant_text = (ace_result.get("answer") or "").strip() or FALLBACK_TEXT
        else:
            profile = get_or_create_profile_for_user(sessionUser)
            memory_obj, _ = Memory.get_or_create_for_profile(profile)
            bullets = memory_obj.retrieve_ranked_bullets(
                query=trimmed,
                learner_id=str(profile.user_id),
                context_scope_id=sessionId,
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

            first_delta_agent_name = (
                responding_agent.get("name", "") if responding_agent else ""
            )
            try:
                for chunk in generate_reply_stream(full_prompt):
                    if isinstance(chunk, dict) and chunk.get("_type") == "usage_metadata":
                        usage_metadata = chunk
                    elif isinstance(chunk, str) and chunk:
                        chunks_buf.append(chunk)
                        delta_idx += 1
                        live_payload = {
                            "type": "delta",
                            "content": chunk,
                            # html left empty so the client renders raw text
                            # until the final `done` payload swaps in the
                            # markdown-rendered HTML. Rendering markdown on
                            # every token is too expensive and flickers.
                            "html": "",
                        }
                        if delta_idx == 1 and first_delta_agent_name:
                            live_payload["agentName"] = first_delta_agent_name
                        yield live_payload
            except Exception as stream_exc:
                _stream_debug_log(
                    f"stream_error session_id={sessionId} error={stream_exc}"
                )
            assistant_text = "".join(chunks_buf).strip() or FALLBACK_TEXT

        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        pipeline_name = "local_qwen" if use_local else "gemini_direct"
        model_used = "qwen3.5-0.8b" if use_local else "gemini-3-flash-preview"
        prompt_tok = usage_metadata.get("prompt_tokens", 0) if usage_metadata else 0
        completion_tok = usage_metadata.get("completion_tokens", 0) if usage_metadata else 0
        total_tok = usage_metadata.get("total_tokens", 0) if usage_metadata else prompt_tok + completion_tok
        try:
            neo4j.create_request_log(
                user_id=sessionProfileId,
                session_id=sessionId,
                request_type="chat",
                model_name=model_used,
                pipeline=pipeline_name,
                status="success",
                latency_ms=elapsed_ms,
                prompt_tokens=prompt_tok,
                completion_tokens=completion_tok,
                total_tokens=total_tok,
                estimated_cost_usd=_estimate_cost(model_used, prompt_tok, completion_tok),
            )
        except Exception:
            pass

        log_event(
            "chat_stream_ace_ok",
            session_id=sessionId,
            answer_len=len(assistant_text),
            pipeline=pipeline_name,
            agent_name=responding_agent.get("name") if responding_agent else None,
        )
        _stream_debug_log(
            "ace_ok "
            f"session_id={sessionId} answer_len={len(assistant_text)} "
            f"pipeline={'local_qwen' if use_local else 'gemini_direct'} "
            f"elapsed_ms={int((time.monotonic() - started_at) * 1000)}"
        )
    except Exception as exc:
        assistant_text = FALLBACK_TEXT
        try:
            neo4j.create_request_log(
                user_id=sessionProfileId,
                session_id=sessionId,
                request_type="chat",
                model_name="gemini-3-flash-preview",
                pipeline="fallback",
                status="error",
                latency_ms=int((time.monotonic() - started_at) * 1000),
                error_type=exc.__class__.__name__,
            )
        except Exception:
            pass
        log_event(
            "chat_stream_ace_failed_fallback",
            session_id=sessionId,
            error_type=exc.__class__.__name__,
            answer_len=len(assistant_text),
        )
        _stream_debug_log(
            "ace_failed_fallback "
            f"session_id={sessionId} answer_len={len(assistant_text)} "
            f"error={exc.__class__.__name__}: {exc} "
            f"elapsed_ms={int((time.monotonic() - started_at) * 1000)}"
        )

    if not assistant_text:
        assistant_text = FALLBACK_TEXT

    assistant_text = _substitute_user_placeholder(assistant_text)
    assistant_text = normalize_mentions(assistant_text)

    agentDisplayName = responding_agent.get("name", "") if responding_agent else ""
    senderAgentId = responding_agent.get("id", "") if responding_agent else None
    assistantMsg = neo4j.create_message(
        session_id=sessionId,
        content=assistant_text,
        created_by=sessionProfileId,
        role="assistant",
        is_ai=True,
        sender_agent_id=str(senderAgentId) if senderAgentId else None,
        sender_agent_name=agentDisplayName,
    )
    assistantMsgId = assistantMsg.get("id", "")

    rendered_full_html = str(render_assistant_markdown_html(assistant_text))

    # If the generator produced no live tokens (fallback / local-model path),
    # send a single catch-up delta with the full content so the client bubble
    # is populated before the done payload swaps in the rendered markdown.
    if chunks_buf == [] and assistant_text:
        yield {
            "type": "delta",
            "content": assistant_text,
            "html": "",
        }

    donePayload = {
        "type": "done",
        "message_id": assistantMsgId,
        "content": assistant_text,
        "html": rendered_full_html,
    }
    if responding_agent:
        donePayload["agentName"] = responding_agent.get("name", "")
        donePayload["agentId"] = responding_agent.get("id", "")

    yield donePayload

    try:
        from app.services import pusher_service
        pusher_service.send_message(sessionId, {
            "messageId": assistantMsgId,
            "content": assistant_text,
            "html": rendered_full_html,
            "role": "assistant",
            "agentName": responding_agent.get("name", "") if responding_agent else None,
            "agentId": responding_agent.get("id", "") if responding_agent else None,
        })
    except Exception:
        pass
    log_event(
        "chat_stream_done",
        session_id=sessionId,
        message_id=assistantMsgId,
        answer_len=len(assistant_text),
        elapsed_ms=int((time.monotonic() - started_at) * 1000),
    )
    _stream_debug_log(
        "done "
        f"session_id={sessionId} message_id={assistantMsgId} "
        f"delta_count={delta_idx or 1} answer_len={len(assistant_text)} "
        f"elapsed_ms={int((time.monotonic() - started_at) * 1000)}"
    )

    maxAgentTurns = max(1, safe_env_int("CHAT_MAX_AGENT_TURNS", 3))
    maxTurnsPerAgent = max(1, safe_env_int("CHAT_MAX_TURNS_PER_AGENT", 2))
    userMentionedInChain = _reply_mentions_user(assistant_text)
    lastAgentMessageId = assistantMsgId
    if responding_agent:
        from .agent_service import parse_agent_mentions, resolve_responding_agents, get_mention_handle
        respondingName = (responding_agent.get("name") or "").lower()
        agentTurnCounts: dict[str, int] = {respondingName: 1} if respondingName else {}
        scheduledCounts: dict[str, int] = {}

        def _can_queue(name_lower: str) -> bool:
            past = agentTurnCounts.get(name_lower, 0)
            pending = scheduledCounts.get(name_lower, 0)
            return past + pending < maxTurnsPerAgent

        def _queue_agent(a: dict) -> None:
            name_lower = a.get("name", "").lower()
            pendingAgents.append(a)
            scheduledCounts[name_lower] = scheduledCounts.get(name_lower, 0) + 1

        pendingAgents = []
        userMentioned = resolve_responding_agents(sessionUser, sessionId, trimmed)
        for a in userMentioned:
            name_lower = a.get("name", "").lower()
            if _can_queue(name_lower):
                _queue_agent(a)

        def _collect_new_mentions(responseText):
            mentions = parse_agent_mentions(responseText)
            if not mentions:
                return
            mentioned = resolve_responding_agents(sessionUser, sessionId, responseText)
            for a in mentioned:
                name_lower = a.get("name", "").lower()
                if _can_queue(name_lower):
                    _queue_agent(a)

        _collect_new_mentions(assistant_text)

        def _maybe_notify_user_mention(responseText, source_agent_name):
            try:
                if not _reply_mentions_user(responseText):
                    return
                from .notification_service import create_notification
                from .models.notification import NotificationType
                create_notification(
                    sessionUser,
                    title=f"{source_agent_name} mentioned you",
                    message=f"{source_agent_name}: {responseText[:180]}",
                    notification_type=NotificationType.AGENT_RESPONSE,
                    related_url=f"/chat/c/{sessionId}/",
                )
            except Exception:
                pass

        if responding_agent:
            _maybe_notify_user_mention(assistant_text, responding_agent.get("name", "Agent"))

        depth = 1
        idx = 0
        while idx < len(pendingAgents) and depth <= maxAgentTurns:
            nextAgent = pendingAgents[idx]
            idx += 1
            nextNameLower = nextAgent.get("name", "").lower()
            prevName = responding_agent.get("name", "Assistant") if responding_agent else "Assistant"
            prevNameLower = prevName.lower()
            isSelfContinuation = nextNameLower == prevNameLower

            scheduledCounts[nextNameLower] = max(0, scheduledCounts.get(nextNameLower, 0) - 1)
            agentTurnCounts[nextNameLower] = agentTurnCounts.get(nextNameLower, 0) + 1

            respondingDesc = responding_agent.get("description", "") if responding_agent else ""
            nextDesc = nextAgent.get("description", "")

            summaryLines = assistant_text.strip().split("\n")
            briefSummary = "\n".join(summaryLines[:8])
            if len(summaryLines) > 8:
                briefSummary += f"\n... ({len(summaryLines) - 8} more lines in conversation history)"

            isLastKnownTurn = idx >= len(pendingAgents)
            isNearLimit = depth >= maxAgentTurns - 1
            respondedNames = sorted(name for name, count in agentTurnCounts.items() if count > 0)
            respondedList = ", ".join(respondedNames) if respondedNames else "none"

            closingRequirement = (
                f"\n\n## MANDATORY CLOSING LINE\n"
                f"Your reply MUST end with a short line addressed to @{userHandle} (the human user). "
                f"- If the task is complete: \"@{userHandle}, this round is done — here's what was accomplished: …\"\n"
                f"- If you are handing to a new agent: \"@{userHandle}, I'm handing this to @NewAgent for the next step.\"\n"
                f"- If you need input: \"@{userHandle}, please confirm …\"\n"
                f"Never address only other agents; the user must always be addressed on the final line."
            )
            if isLastKnownTurn or isNearLimit:
                closingRequirement += (
                    f"\n\nIMPORTANT: No agents are queued after you. You MUST conclude the task, "
                    f"summarize what was accomplished, and close with a line addressed to @{userHandle}."
                )

            if isSelfContinuation:
                agentReply = (
                    f"[Agent Self-Continuation]\n"
                    f"You ({nextAgent['name']}) just wrote a message that delegated the next step back "
                    f"to yourself (e.g. \"@{get_mention_handle(nextAgent['name'])} ...\" or "
                    f"\"Next focus: @{get_mention_handle(nextAgent['name'])}\").\n"
                    f"You are that agent. Continue the work yourself in THIS turn and produce the "
                    f"concrete deliverable you announced — do not announce it again, do not "
                    f"@mention yourself again, do not hand off further.\n"
                    f"Turn: {depth}/{maxAgentTurns}\n\n"
                    f"## Your previous message\n"
                    f"{briefSummary}\n\n"
                    f"## Original user request\n"
                    f"{trimmed}\n\n"
                    f"## Instructions\n"
                    f"Deliver the output directly. If you planned to draft questions, write the "
                    f"questions now. If you planned to review, do the review now. Do NOT write "
                    f"another plan; execute."
                    f"{closingRequirement}"
                )
            else:
                agentReply = (
                    f"[Agent Handoff Brief]\n"
                    f"From: {prevName} ({respondingDesc})\n"
                    f"To: {nextAgent['name']} ({nextDesc})\n"
                    f"Turn: {depth}/{maxAgentTurns}\n\n"
                    f"## Summary of previous agent's work\n"
                    f"{briefSummary}\n\n"
                    f"## Original user request\n"
                    f"{trimmed}\n\n"
                    f"## Agents who already responded (DO NOT @mention them again)\n"
                    f"{respondedList}\n\n"
                    f"## Instructions\n"
                    f"The full conversation history is available in [Recent Conversation] above. "
                    f"Review it for complete details from previous agents.\n"
                    f"Continue the task based on your expertise. "
                    f"Do NOT @mention agents who already responded (listed above). "
                    f"Do NOT @mention yourself — you are the current speaker; produce the "
                    f"deliverable directly instead of announcing it. "
                    f"If you need NEW agents who have not responded yet, @mention them."
                    f"{closingRequirement}"
                )
            lastPayload = None
            for payload in _agent_to_agent_turn(session, agentReply, nextAgent, depth, maxAgentTurns, None, userDisplayName=userDisplayName):
                lastPayload = payload
                yield payload
            responding_agent = nextAgent
            if isinstance(lastPayload, dict):
                assistant_text = lastPayload.get("content", "")
                lastAgentMessageId = lastPayload.get("message_id", lastAgentMessageId)
            else:
                assistant_text = ""
            if _reply_mentions_user(assistant_text):
                userMentionedInChain = True
            _collect_new_mentions(assistant_text)
            _maybe_notify_user_mention(assistant_text, nextAgent.get("name", "Agent"))
            depth += 1

        if depth > 1 and not _reply_mentions_user(assistant_text):
            lastAgentName = responding_agent.get("name", "Agent") if responding_agent else "Agent"
            agentCount = max(depth - 1, 0)
            closing = (
                f"\n\n@{userHandle}, "
                f"{lastAgentName}"
                + (f" and {agentCount} other agent(s)" if agentCount > 0 else "")
                + " finished this round of work. Please review the conversation above and let me know if you'd like any follow-up or adjustments."
            )
            updatedText = (assistant_text or "").rstrip() + closing
            try:
                neo4j.edit_message(lastAgentMessageId, updatedText)
            except Exception:
                pass
            assistant_text = updatedText
            userMentionedInChain = True
            yield {
                "type": "delta",
                "agentName": lastAgentName,
                "message_id": lastAgentMessageId,
                "content": closing,
                "html": str(render_assistant_markdown_html(updatedText)),
            }

        if depth > 1:
            agentNames = [a.get("name", "") for a in pendingAgents[:depth - 1] if a.get("name")]
            lastAgentName = responding_agent.get("name", "Agent") if responding_agent else "Agent"
            try:
                from .notification_service import create_notification
                from .models.notification import NotificationType
                create_notification(
                    sessionUser,
                    title=f"{lastAgentName} mentioned you",
                    message=f"Hi @{userHandle}, {lastAgentName} and {len(agentNames)} agent(s) finished working on your request. Review the conversation for results.",
                    notification_type=NotificationType.AGENT_RESPONSE,
                    related_url=f"/chat/c/{sessionId}/",
                )
            except Exception:
                pass

    if not use_local and assistant_text and assistant_text != FALLBACK_TEXT:
        import threading

        def _run_post_response_learning():
            try:
                ace_result = run_ace_chat_turn(session, trimmed, agent=responding_agent, doc_chunks=doc_chunks)
                log_event(
                    "chat_post_response_memory",
                    session_id=sessionId,
                    ace_delta=ace_result.get("ace_delta"),
                    quality_gate=ace_result.get("quality_gate", {}).get("should_apply_update"),
                )
            except Exception as exc:
                log_event(
                    "chat_post_response_memory_error",
                    session_id=sessionId,
                    error_type=exc.__class__.__name__,
                    error=str(exc)[:500],
                )

        threading.Thread(target=_run_post_response_learning, daemon=True).start()


def _agent_to_agent_turn(session, prompt, agent, depth, maxDepth=8, visitedAgents=None, userDisplayName=""):
    from app.services.gemini import generate_reply_stream

    sessionId = _session_id(session)
    sessionUser = session.get("_user") if isinstance(session, dict) else session.user.user
    sessionProfileId = session.get("_profile_id") if isinstance(session, dict) else str(session.user.pk)

    systemPrompt = agent.get("systemPrompt", "")
    agentName = agent.get("name", "Agent")

    contextParts = []
    if systemPrompt:
        contextParts.append(f"[System Instructions]\n{systemPrompt}")

    conversationContext = _build_conversation_context(session)
    if conversationContext:
        contextParts.append(f"[Recent Conversation]\n{conversationContext}")

    try:
        profile = get_or_create_profile_for_user(sessionUser)
        memory_obj, _ = Memory.get_or_create_for_profile(profile)
        bullets = memory_obj.retrieve_ranked_bullets(
            query=prompt,
            learner_id=str(profile.user_id),
            context_scope_id=sessionId,
            top_k=5,
            min_learned=2,
            base_strength=100.0,
            relevance_w=0.60,
            strength_w=0.20,
            type_w=0.20,
            seed_penalty=0.25,
            learned_bonus=0.08,
        )
        guidance = _build_guidance_from_bullets(bullets)
        if guidance:
            contextParts.append(f"[Relevant Knowledge]\n{guidance}")
    except Exception:
        pass

    if depth <= 4:
        try:
            docChunks = retrieve_relevant_document_chunks(sessionProfileId, prompt, top_k=2)
            if docChunks:
                docText = "\n".join([f"From \"{c['filename']}\":\n  {c['chunk']}" for c in docChunks])
                contextParts.append(f"[Relevant Documents]\n{docText}")
        except Exception:
            pass

    contextParts.append(f"[Agent Message]\n{prompt}")
    fullPrompt = "\n\n".join(contextParts)

    chunks_buf = []
    try:
        for chunk in generate_reply_stream(fullPrompt):
            if isinstance(chunk, str) and chunk:
                chunks_buf.append(chunk)
    except Exception:
        pass
    replyText = "".join(chunks_buf).strip() or FALLBACK_TEXT
    if userDisplayName and userDisplayName != "User":
        replyText = re.sub(r"(?<!\w)@User(?!\w)", f"@{userDisplayName}", replyText)
    replyText = normalize_mentions(replyText)

    senderAgentId = agent.get("id", "")
    assistantMsg = neo4j.create_message(
        session_id=sessionId,
        content=replyText,
        created_by=sessionProfileId,
        role="assistant",
        is_ai=True,
        sender_agent_id=str(senderAgentId) if senderAgentId else None,
        sender_agent_name=agentName,
    )
    assistantMsgId = assistantMsg.get("id", "")

    yield {
        "type": "agent_turn",
        "agentName": agentName,
        "agentId": agent.get("id", ""),
        "turn": depth,
        "maxTurns": maxDepth,
        "message_id": assistantMsgId,
        "content": replyText,
        "html": str(render_assistant_markdown_html(replyText)),
    }


def get_memory_list_data(user, search_query="", memory_type="", sort_key="created"):
    bulletsList = _get_memory_bullets_for_user(user)

    query = (search_query or "").strip()
    memory_type = (memory_type or "").strip()
    sort_key = (sort_key or "created").strip()

    bulletsList = _apply_memory_bullet_filters(
        bulletsList,
        q=query,
        memory_type=memory_type,
    )

    for b in bulletsList:
        b["affect"] = (b.get("helpfulCount", 0) or 0) - (b.get("harmfulCount", 0) or 0)

    sortMap = {
        "created": ("createdAt", True, "Created time"),
        "strength": ("strength", True, "Strength"),
        "affect": ("affect", True, "Affect"),
    }
    sortField, sortReverse, sortLabel = sortMap.get(sort_key, sortMap["created"])
    activeSort = sort_key if sort_key in sortMap else "created"

    bulletsList.sort(key=lambda b: (b.get(sortField, "") or "", b.get("lastAccessed", "") or ""), reverse=sortReverse)

    memoryTypeChoices = [(1, "Semantic"), (2, "Episodic"), (3, "Procedural")]

    return {
        "queryset": bulletsList,
        "active_memory_type": memory_type,
        "search_query": query,
        "sort_label": sortLabel,
        "active_sort": activeSort,
        "memory_type_choices": memoryTypeChoices,
    }


def get_memory_summary(user):
    bulletsList = _get_memory_bullets_for_user(user)

    typeCounts = defaultdict(int)
    strengths = []
    totalHelpful = 0
    totalHarmful = 0
    for b in bulletsList:
        typeCounts[b.get("memoryType", 0)] += 1
        strengths.append(b.get("strength", 0) or 0)
        totalHelpful += b.get("helpfulCount", 0) or 0
        totalHarmful += b.get("harmfulCount", 0) or 0

    typeSummary = [
        {"memory_type": k, "label": MEMORY_TYPE_LABELS.get(k, str(k)), "count": v}
        for k, v in sorted(typeCounts.items())
    ]

    avgStrength = (sum(strengths) / len(strengths)) if strengths else None
    maxStrength = max(strengths) if strengths else None
    minStrength = min(strengths) if strengths else None

    return {
        "total_count": len(bulletsList),
        "type_summary": typeSummary,
        "avg_strength": avgStrength,
        "max_strength": maxStrength,
        "min_strength": minStrength,
        "total_helpful": totalHelpful,
        "total_harmful": totalHarmful,
    }


from .chart_service import (
    get_memory_type_chart_png,
    get_memory_strength_chart_png,
    get_activity_chart_png,
    get_latency_over_time_chart_png,
    get_latency_by_model_chart_png,
    get_error_rate_chart_png,
    get_daily_cost_chart_png,
    get_token_usage_chart_png,
    get_cost_by_model_chart_png,
)


def get_api_memory_bullets_payload(user, q="", memory_type="", topic="", strength_min="", limit=100):
    bulletsList = _get_memory_bullets_for_user(user)
    bulletsList = _apply_memory_bullet_filters(
        bulletsList,
        q=q,
        memory_type=memory_type,
        topic=topic,
        strength_min=strength_min,
    )

    data = []
    for b in bulletsList[:limit]:
        createdAt = b.get("createdAt", "")
        if hasattr(createdAt, "isoformat"):
            createdAt = createdAt.isoformat()
        lastAccessed = b.get("lastAccessed", "")
        if hasattr(lastAccessed, "isoformat"):
            lastAccessed = lastAccessed.isoformat()
        data.append({
            "id": b.get("id", ""),
            "content": b.get("content", ""),
            "memory_type": MEMORY_TYPE_LABELS.get(b.get("memoryType", 0), str(b.get("memoryType", ""))),
            "topic": b.get("topic", ""),
            "strength": b.get("strength", 0),
            "helpful_count": b.get("helpfulCount", 0),
            "harmful_count": b.get("harmfulCount", 0),
            "created_at": str(createdAt),
            "last_accessed": str(lastAccessed),
        })
    return {"count": len(data), "results": data}


def get_api_sessions_payload(user, q="", limit=50):
    sessions = _get_session_queryset_for_user(user)
    if q:
        lowerQ = q.strip().lower()
        sessions = [s for s in sessions if lowerQ in (s.get("title", "") or "").lower()]
    data = []
    for s in sessions[:limit]:
        createdAt = s.get("createdAt", "")
        if hasattr(createdAt, "isoformat"):
            createdAt = createdAt.isoformat()
        updatedAt = s.get("updatedAt", "")
        if hasattr(updatedAt, "isoformat"):
            updatedAt = updatedAt.isoformat()
        sessionId = s.get("id", "")
        data.append({
            "id": sessionId,
            "title": s.get("title", ""),
            "created_at": str(createdAt),
            "updated_at": str(updatedAt),
            "url": f"/chat/c/{sessionId}/",
        })
    return {"count": len(data), "results": data}


def get_api_messages_payload(user, session_id, role_filter=""):
    _get_session_or_404_for_user(user, session_id, with_messages=False)

    messages = neo4j.get_messages_for_session(str(session_id))
    if role_filter.strip().isdigit():
        targetRole = role_filter.strip()
        messages = [m for m in messages if str(m.get("role", "")) == targetRole]

    roleDisplay = {"user": "User", "assistant": "Assistant", "system": "System"}
    data = []
    for m in messages:
        createdAt = m.get("createdAt", "")
        if hasattr(createdAt, "isoformat"):
            createdAt = createdAt.isoformat()
        data.append({
            "id": m.get("id", ""),
            "role": roleDisplay.get(str(m.get("role", "")), str(m.get("role", ""))),
            "content": m.get("content", ""),
            "created_at": str(createdAt),
        })
    return {"session_id": session_id, "count": len(data), "messages": data}
