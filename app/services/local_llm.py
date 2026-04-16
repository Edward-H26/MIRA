import re
import threading
from pathlib import Path
from typing import Any

from django.conf import settings

_model: Any | None = None
_tokenizer: Any | None = None
_load_lock = threading.Lock()
_MODEL_ID = "Qwen/Qwen3.5-0.8B"
_CACHE_DIR_NAMES = (
    "Qwen__Qwen3_5-0_8B",
    "models--Qwen--Qwen3.5-0.8B",
)
_load_failed = False
_availability_cached: bool | None = None

ACE_PREPROCESS_TEMPLATE = """You are the Reflector in an Agentic Context Engineering system.

Your role is to analyze the learned experience and conversation context to extract concrete, actionable lessons that will help generate the best response.

## Learned Experience from Prior Conversations
{guidance}

## Recent Conversation Context
{conversation_context}

## Current Question
{question}

## Instructions
Analyze the learned experience and conversation context above and extract specific lessons:

1. **Successful Strategies**: What specific approaches, tools, or reasoning patterns worked well?
2. **Failure Modes**: What specific mistakes or pitfalls occurred? What should be avoided?
3. **Domain Insights**: What domain-specific knowledge or concepts were crucial?
4. **Tool Usage Patterns**: How should tools be used effectively?

For EACH lesson:
- Be SPECIFIC and CONCRETE (not vague generalizations)
- Include EXAMPLES or CONTEXT when possible
- Make it ACTIONABLE (something that can guide future attempts)
- Keep it FOCUSED on one insight

Output your response as a JSON object:
{{
  "lessons": [
    {{
      "content": "Specific lesson content here",
      "type": "success" or "failure" or "domain" or "tool",
      "tags": ["tag1", "tag2"]
    }},
    ...
  ],
  "reflection": "Brief overall reflection on what was learned"
}}

Output ONLY valid JSON, nothing else."""


def _get_cache_root() -> Path:
    return settings.BASE_DIR / "llm_test" / "cache" / "huggingface-models"


def _get_cache_paths() -> tuple[Path, ...]:
    cache_root = _get_cache_root()
    return tuple(cache_root / dir_name for dir_name in _CACHE_DIR_NAMES)


def is_available() -> bool:
    global _availability_cached
    if _model is not None and _tokenizer is not None:
        return True
    if _load_failed:
        return False
    if _availability_cached is not None:
        return _availability_cached

    customCachePaths = _get_cache_paths()
    foundInCustom = any(
        p.exists() and any(p.iterdir()) for p in customCachePaths
    )
    if foundInCustom:
        _availability_cached = True
        return True

    try:
        from transformers import AutoConfig
        AutoConfig.from_pretrained(_MODEL_ID)
        _availability_cached = True
    except Exception:
        _availability_cached = False
    return _availability_cached


def is_loaded() -> bool:
    return _model is not None and _tokenizer is not None


def _candidate_devices() -> tuple[str, ...]:
    import torch

    devices: list[str] = []
    if torch.cuda.is_available():
        devices.append("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        devices.append("mps")
    devices.append("cpu")
    return tuple(devices)


def _get_torch_dtype(device: str):
    import torch
    import os

    if device in {"cuda", "mps"}:
        return torch.float16
    if os.getenv("CHAT_LOCAL_MODEL_FP16", "0").strip().lower() in {"1", "true", "yes"}:
        return torch.float16
    return torch.float32


def _load_model_for_device(device: str):
    from transformers import AutoModelForCausalLM, AutoTokenizer

    cache_root = _get_cache_root()
    customCacheExists = any(
        p.exists() and any(p.iterdir()) for p in _get_cache_paths()
    )

    loadKwargs = {"trust_remote_code": True}
    if customCacheExists:
        loadKwargs["cache_dir"] = str(cache_root)
        loadKwargs["local_files_only"] = True

    tokenizer = AutoTokenizer.from_pretrained(_MODEL_ID, **loadKwargs)

    model_kwargs = {
        **loadKwargs,
        "torch_dtype": _get_torch_dtype(device),
    }
    if device == "cuda":
        model_kwargs["device_map"] = "auto"
    model = AutoModelForCausalLM.from_pretrained(_MODEL_ID, **model_kwargs)
    if device != "cuda":
        model = model.to(device)
    model.eval()

    if tokenizer.pad_token_id is None and tokenizer.eos_token is not None:
        tokenizer.pad_token = tokenizer.eos_token

    return model, tokenizer


def _get_model_and_tokenizer():
    global _model, _tokenizer, _load_failed

    if _model is not None and _tokenizer is not None:
        return _model, _tokenizer

    with _load_lock:
        if _model is not None and _tokenizer is not None:
            return _model, _tokenizer
        if _load_failed:
            raise RuntimeError("Local LLM is unavailable")
        if not is_available():
            raise FileNotFoundError("Local LLM cache is unavailable")

        last_error: Exception | None = None
        for device in _candidate_devices():
            try:
                loaded_model, loaded_tokenizer = _load_model_for_device(device)
                _model = loaded_model
                _tokenizer = loaded_tokenizer
                return _model, _tokenizer
            except Exception as exc:
                last_error = exc

        _load_failed = True
        raise RuntimeError("Failed to load local LLM") from last_error


def _get_model_device(model) -> Any:
    return next(model.parameters()).device


def preprocess_prompt(user_text: str, guidance: str = "", conversation_context: str = "") -> str | None:
    trimmed = (user_text or "").strip()
    if not trimmed:
        return None

    try:
        import torch

        model, tokenizer = _get_model_and_tokenizer()

        guidance_block = guidance.strip() if guidance else "No prior experience available."
        context_block = conversation_context.strip() if conversation_context else "No prior conversation."
        full_input = ACE_PREPROCESS_TEMPLATE.format(
            guidance=guidance_block,
            conversation_context=context_block,
            question=trimmed,
        )

        inputs = tokenizer(full_input, return_tensors="pt", truncation=True, max_length=2048)
        model_device = _get_model_device(model)
        inputs = {key: value.to(model_device) for key, value in inputs.items()}

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=384,
                do_sample=False,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )

        generated = outputs[0][inputs["input_ids"].shape[1]:]
        preprocessed = tokenizer.decode(generated, skip_special_tokens=True).strip()
        preprocessed = re.sub(r"<think>.*?</think>", "", preprocessed, flags=re.DOTALL).strip()
        return preprocessed or None
    except Exception as exc:
        from memoria.event_log import log_event
        log_event("local_llm_preprocess_error", error_type=exc.__class__.__name__)
        return None


RESPONSE_TEMPLATE = """You are a helpful AI assistant called Memoria. Answer the user's question clearly and concisely.

## Relevant Context
{guidance}

## Conversation History
{conversation_context}

## User Question
{question}

## Instructions
Provide a direct, helpful answer. Be concise but thorough."""


def generate_response(user_text: str, guidance: str = "", conversation_context: str = "", system_prompt: str = "") -> str | None:
    trimmed = (user_text or "").strip()
    if not trimmed:
        return None

    try:
        import torch

        model, tokenizer = _get_model_and_tokenizer()

        guidanceBlock = guidance.strip() if guidance else ""
        contextBlock = conversation_context.strip() if conversation_context else ""
        baseIdentity = system_prompt.strip() if system_prompt else "You are a helpful AI assistant. Answer concisely."
        systemParts = [baseIdentity]
        if guidanceBlock:
            systemParts.append(f"Context: {guidanceBlock[:500]}")
        if contextBlock:
            systemParts.append(f"History: {contextBlock[:500]}")
        systemMsg = "\n".join(systemParts)

        messages = [
            {"role": "system", "content": systemMsg},
            {"role": "user", "content": trimmed},
        ]
        full_input = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

        inputs = tokenizer(full_input, return_tensors="pt", truncation=True, max_length=2048)
        model_device = _get_model_device(model)
        inputs = {key: value.to(model_device) for key, value in inputs.items()}

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=256,
                do_sample=True,
                temperature=0.6,
                top_p=0.9,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )

        generated = outputs[0][inputs["input_ids"].shape[1]:]
        response = tokenizer.decode(generated, skip_special_tokens=True).strip()
        response = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()
        return response or None
    except Exception as exc:
        from memoria.event_log import log_event
        log_event("local_llm_generate_error", error_type=exc.__class__.__name__)
        return None
