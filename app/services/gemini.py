import os
import threading

from google import genai
from google.genai import types
from django.conf import settings

GEMINI_REQUEST_TIMEOUT_MS = 30_000
GEMINI_CLASSIFIER_TIMEOUT_MS = 8_000
DEFAULT_STREAM_MAX_OUTPUT_TOKENS = 2048


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


_GEMINI_CONCURRENCY_LIMIT = max(1, _int_env("GEMINI_CONCURRENCY_LIMIT", 15))
_GEMINI_CLASSIFIER_CONCURRENCY_LIMIT = max(1, _int_env("GEMINI_CLASSIFIER_CONCURRENCY", 10))
_GEMINI_SEMAPHORE = threading.BoundedSemaphore(_GEMINI_CONCURRENCY_LIMIT)
_GEMINI_CLASSIFIER_SEMAPHORE = threading.BoundedSemaphore(
    _GEMINI_CLASSIFIER_CONCURRENCY_LIMIT
)


class _SemaphoreGuard:
    """Context manager that wraps a BoundedSemaphore with an acquire timeout.

    When the semaphore cannot be acquired within ``timeout`` seconds, the
    generation raises ``TimeoutError`` rather than hanging indefinitely. This
    prevents runaway queues when Gemini is saturated upstream — callers see a
    fast failure and can fall back to the local model or report an error to
    the user.
    """

    def __init__(self, semaphore: threading.BoundedSemaphore, timeout: float):
        self._semaphore = semaphore
        self._timeout = timeout
        self._acquired = False

    def __enter__(self):
        if not self._semaphore.acquire(timeout=self._timeout):
            raise TimeoutError(
                "Timed out waiting for Gemini capacity; server is saturated."
            )
        self._acquired = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._acquired:
            self._semaphore.release()
            self._acquired = False
        return False


def _gemini_slot(kind: str = "chat"):
    timeout = float(_int_env("GEMINI_SEMAPHORE_ACQUIRE_TIMEOUT", 30))
    if kind == "classifier":
        return _SemaphoreGuard(_GEMINI_CLASSIFIER_SEMAPHORE, timeout=timeout)
    return _SemaphoreGuard(_GEMINI_SEMAPHORE, timeout=timeout)


client = genai.Client(
    api_key=settings.GEMINI_API_KEY,
    http_options=types.HttpOptions(timeout=GEMINI_REQUEST_TIMEOUT_MS),
)
MODEL_ID = "gemini-3-flash-preview"
CLASSIFIER_MODEL_ID = "gemini-3.1-flash-lite-preview"

CLASSIFIER_SYSTEM_INSTRUCTION = (
    "You are a query complexity classifier. Respond with exactly one word: "
    "SIMPLE or COMPLEX.\n\n"
    "SIMPLE: factual lookups, greetings, single-topic questions, short requests, "
    "casual conversation, definitions, yes/no questions.\n\n"
    "COMPLEX: multi-step reasoning, comparisons across categories, analytical tasks, "
    "planning with constraints, queries requiring multiple pieces of information, "
    "queries with conditions like 'must', 'at least', 'compare', 'evaluate', "
    "'step by step', or 'then'."
)


def _build_generation_config(
    *,
    system_instruction: str = "",
    max_output_tokens: int | None = None,
    thinking_level: str = "low",
):
    config_kwargs = {
        "thinking_config": types.ThinkingConfig(thinking_level=thinking_level),
    }
    if system_instruction:
        config_kwargs["system_instruction"] = system_instruction
    if max_output_tokens is not None:
        config_kwargs["max_output_tokens"] = max_output_tokens
    return types.GenerateContentConfig(**config_kwargs)


def _extract_response_text(response) -> str:
    text = getattr(response, "text", None)
    if text:
        return text.strip()

    chunks = []
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            part_text = getattr(part, "text", None)
            if part_text:
                chunks.append(part_text)
    return "".join(chunks).strip()


def generate_reply_stream(user_text: str, *, max_output_tokens: int = DEFAULT_STREAM_MAX_OUTPUT_TOKENS):
    with _gemini_slot("chat"):
        response = client.models.generate_content_stream(
            model=MODEL_ID,
            contents=user_text,
            config=_build_generation_config(max_output_tokens=max_output_tokens),
        )
        usage = None
        for chunk in response:
            text = getattr(chunk, "text", None)
            if text:
                yield text
            meta = getattr(chunk, "usage_metadata", None)
            if meta:
                usage = meta
    if usage:
        promptTokens = getattr(usage, "prompt_token_count", 0) or 0
        completionTokens = getattr(usage, "candidates_token_count", 0) or 0
        thinkingTokens = getattr(usage, "thoughts_token_count", 0) or 0
        totalTokens = getattr(usage, "total_token_count", 0) or 0
        yield {
            "_type": "usage_metadata",
            "prompt_tokens": promptTokens,
            "completion_tokens": completionTokens,
            "thinking_tokens": thinkingTokens,
            "total_tokens": totalTokens if totalTokens else promptTokens + completionTokens,
        }


def generate_reply_text(user_text: str):
    chunks = []
    for chunk in generate_reply_stream(user_text):
        if isinstance(chunk, str) and chunk:
            chunks.append(chunk)
    return "".join(chunks).strip()


def generate_structured_text(
    prompt: str,
    *,
    system_instruction: str = "",
    max_output_tokens: int = 512,
    thinking_level: str = "low",
):
    with _gemini_slot("chat"):
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config=_build_generation_config(
                system_instruction=system_instruction,
                max_output_tokens=max_output_tokens,
                thinking_level=thinking_level,
            ),
        )
    return _extract_response_text(response)


MULTIMODAL_OCR_INSTRUCTION = (
    "You are an OCR engine. Extract ALL text visible in the image exactly as it appears, "
    "preserving line breaks, numbers, dates, and punctuation. Do not summarize, add "
    "commentary, or translate. If the content looks like a receipt, invoice, form, or "
    "contract, keep the structure intact. If no text is visible, return an empty string."
)


def extract_text_multimodal(image_bytes: bytes, mime_type: str = "image/png") -> str:
    if not image_bytes:
        return ""
    config = types.GenerateContentConfig(
        max_output_tokens=4096,
        system_instruction=MULTIMODAL_OCR_INSTRUCTION,
        thinking_config=types.ThinkingConfig(thinking_level="low"),
    )
    with _gemini_slot("chat"):
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                "Extract all text from this image.",
            ],
            config=config,
        )
    return _extract_response_text(response)


def classify_prompt(user_text: str) -> str:
    trimmed = (user_text or "").strip()
    if not trimmed:
        return "simple"

    try:
        config = types.GenerateContentConfig(
            max_output_tokens=8,
            system_instruction=CLASSIFIER_SYSTEM_INSTRUCTION,
        )
        with _gemini_slot("classifier"):
            response = client.models.generate_content(
                model=CLASSIFIER_MODEL_ID,
                contents=trimmed,
                config=config,
            )
        result = _extract_response_text(response).upper().strip()
        if "COMPLEX" in result:
            return "complex"
        return "simple"
    except Exception:
        from app.services.classifier import classify_prompt as regex_classify
        return regex_classify(trimmed)
