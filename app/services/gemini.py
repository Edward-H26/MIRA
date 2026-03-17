from google import genai
from google.genai import types
from django.conf import settings

client = genai.Client(api_key=settings.GEMINI_API_KEY)
MODEL_ID = "gemini-3-flash-preview"


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


def generate_reply_stream(user_text: str):
    response = client.models.generate_content_stream(
        model=MODEL_ID,
        contents=user_text,
        config=_build_generation_config(),
    )
    for chunk in response:
        text = getattr(chunk, "text", None)
        if text:
            yield text


def generate_reply_text(user_text: str):
    chunks = []
    for chunk in generate_reply_stream(user_text):
        if chunk:
            chunks.append(chunk)
    return "".join(chunks).strip()


def generate_structured_text(
    prompt: str,
    *,
    system_instruction: str = "",
    max_output_tokens: int = 512,
    thinking_level: str = "low",
):
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
