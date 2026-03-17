import json
import os
import re

from memoria.event_log import log_event
from app.services.gemini import generate_reply_text, generate_structured_text
from .models import Memory
from .models.memory_bullet import MemoryBullet
from .models.message import Role

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
GENERIC_LESSON_PATTERNS = (
    "provide a clear answer like:",
    "when handling ",
    "the answer is ",
)
FACT_RECALL_PATTERNS = (
    "what is my name",
    "who am i",
    "what did i say",
    "what was my",
    "remind me what",
)
REFLECTOR_SYSTEM_INSTRUCTION = (
    "You are a curation assistant. Output only valid JSON that matches the requested schema. "
    "Do not include markdown fences or explanatory prose."
)
REFLECTOR_PROMPT = """You are the Reflector in an Agentic Context Engineering system.

Your role is to analyze the execution trace and extract concrete, actionable lessons that can help improve future performance.

## Execution Trace
{trace}

## Current Question
{question}

## Model's Answer
{model_answer}

## Instructions
Analyze the execution trace above and extract specific lessons:

1. Successful strategies that improved the answer
2. Failure modes or mistakes to avoid
3. Domain insights that should be remembered
4. Tool or context usage patterns that should be reused

For each lesson:
- Be specific and concrete
- Keep it reusable across future turns
- Avoid copying the final answer verbatim
- Keep it focused on one insight

Return JSON with this exact shape:
{{
  "lessons": [
    {{
      "content": "Specific lesson content",
      "type": "success",
      "tags": ["tag1", "tag2"]
    }}
  ]
}}
"""

PLANNER_ACTIONS = {
    "direct": {"rounds": 1, "candidates": 1},
    "explore": {"rounds": 1, "candidates": 2},
    "refine": {"rounds": 2, "candidates": 2},
    "deep_refine": {"rounds": 2, "candidates": 3},
}
ACTION_LEVELS = ["direct", "explore", "refine", "deep_refine"]
META_STRATEGY_SEEDS = [
    "Before answering, re-read constraints and follow explicit context rules.",
    "Follow the required output format exactly and avoid extra text.",
    "Prefer context-grounded answers over assumptions.",
]


def _safe_env_float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _safe_env_int(name, default):
    try:
        value = int(os.getenv(name, str(default)))
    except Exception:
        return default
    return value if value > 0 else default


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


def _tokenize(text):
    return TOKEN_PATTERN.findall((text or "").lower())


def _normalize_tags(tags):
    normalized = []
    seen = set()
    for tag in tags or []:
        slug = re.sub(r"[^a-z0-9]+", "_", str(tag).strip().lower()).strip("_")
        if not slug or slug in {"semantic", "episodic", "procedural"} or slug in seen:
            continue
        seen.add(slug)
        normalized.append(slug)
    return normalized


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def _compute_shaped_reward(step_score, output_valid, quality_gate_applied, recursion_improved=False, terminal_score=None, step_confidence=0.7):
    clipped_step = _clamp(step_score)
    clipped_confidence = _clamp(step_confidence)
    output_term = 1.0 if output_valid else 0.0
    gate_term = 1.0 if quality_gate_applied else 0.0
    recursion_term = 1.0 if recursion_improved else 0.0

    proxy_reward = _clamp(
        0.55 * clipped_step + 0.20 * output_term + 0.15 * gate_term + 0.10 * recursion_term
    )

    if terminal_score is None:
        final_reward = proxy_reward
    else:
        final_reward = _clamp(0.60 * proxy_reward + 0.40 * _clamp(float(terminal_score)))

    return {
        "proxy_reward": proxy_reward,
        "final_reward": final_reward,
        "confidence": clipped_confidence,
    }


def guidance_from_bullets(bullets):
    if not bullets:
        return ""
    lines = ["=== Guidance from Prior Experience ==="]
    for idx, bullet in enumerate(bullets, 1):
        lines.append(f"{idx}. [+{bullet.helpful_count}/-{bullet.harmful_count}] {bullet.content}")
    lines.append("===")
    return "\n".join(lines)


def _build_recent_conversation_context(session):
    max_messages = _safe_env_int("ACE_CONTEXT_MAX_MESSAGES", 12)
    max_messages = min(max(max_messages, 2), 40)

    rows = list(
        session.messages.exclude(role=Role.SYSTEM)
        .order_by("-created_at")
        .values_list("role", "content")[:max_messages]
    )
    if not rows:
        return ""

    rows.reverse()
    role_name_map = {
        int(Role.USER): "User",
        int(Role.ASSISTANT): "Assistant",
    }
    lines = ["=== Recent Conversation ==="]
    for role, content in rows:
        speaker = role_name_map.get(int(role), "Other")
        normalized = (content or "").strip()
        if not normalized:
            continue
        lines.append(f"{speaker}: {normalized}")
    lines.append("===")
    return "\n".join(lines)


def _candidate_score(question, content):
    if not (content or "").strip():
        return 0.0, 0.0
    overlap = MemoryBullet.text_similarity(question, content)
    token_score = min(len(_tokenize(content)) / 40.0, 1.0)
    score = max(0.0, min(1.0, 0.55 * overlap + 0.25 + 0.20 * token_score))
    confidence = max(0.0, min(1.0, 0.65 * score + 0.35 * token_score))
    return score, confidence


def _run_recursive_reasoning(question, base_prompt, action_id):
    config = PLANNER_ACTIONS.get(action_id, PLANNER_ACTIONS["direct"])
    best_text = ""
    best_score = -1.0
    best_conf = 0.0

    for round_idx in range(config["rounds"]):
        for candidate_idx in range(config["candidates"]):
            if round_idx == 0 and candidate_idx == 0:
                prompt = base_prompt
            else:
                critique = (
                    "Refine the answer. Keep it concise, accurate, and follow constraints."
                    if candidate_idx == 0
                    else "Provide an alternative improved final answer."
                )
                prompt = f"{base_prompt}\n\n{critique}\n\nCurrent best:\n{best_text}"
            content = (generate_reply_text(prompt) or "").strip()
            score, conf = _candidate_score(question, content)
            if score > best_score:
                best_score = score
                best_text = content
                best_conf = conf
        if round_idx > 0 and best_score >= 0.75:
            break

    recursion = {
        "rounds_planned": config["rounds"],
        "candidates_per_round": config["candidates"],
        "final_score": max(best_score, 0.0),
        "improved": config["rounds"] > 1,
    }
    return best_text, best_conf, recursion


def _lesson_overlap_score(question, lesson_content):
    question_tokens = set(_tokenize(question))
    lesson_tokens = set(_tokenize(lesson_content))
    if not question_tokens or not lesson_tokens:
        return 0.0
    return len(question_tokens.intersection(lesson_tokens)) / len(question_tokens.union(lesson_tokens))


def _lesson_relevance_score(question, lesson_content):
    question_tokens = set(_tokenize(question))
    lesson_tokens = set(_tokenize(lesson_content))
    if not question_tokens or not lesson_tokens:
        return 0.0
    intersection = len(question_tokens.intersection(lesson_tokens))
    if intersection == 0:
        return 0.0
    lexical_jaccard = intersection / len(question_tokens.union(lesson_tokens))
    precision = intersection / max(len(lesson_tokens), 1)
    recall = intersection / max(len(question_tokens), 1)
    f1_overlap = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    coverage = intersection / max(min(len(question_tokens), len(lesson_tokens)), 1)
    return min(0.50 * lexical_jaccard + 0.30 * f1_overlap + 0.20 * coverage, 1.0)


def _lesson_quality_score(lesson):
    content = (lesson.get("content") or "").strip()
    if not content:
        return 0.0
    token_score = min(len(_tokenize(content)) / 20.0, 1.0) * 0.6
    tags_score = 0.2 if lesson.get("tags") else 0.0
    lesson_type = (lesson.get("type") or "").lower()
    type_score = 0.2 if lesson_type in {"success", "failure", "domain", "tool"} else 0.0
    return min(token_score + tags_score + type_score, 1.0)


def _lesson_confidence_score(lesson, relevance_score, lesson_score, verifier_score):
    if verifier_score <= 0.0:
        verifier_score = 0.5 * lesson_score + 0.5 * relevance_score
    return min(
        0.45 * lesson_score + 0.40 * relevance_score + 0.15 * max(min(verifier_score, 1.0), 0.0),
        1.0,
    )


def _apply_quality_gate(question, model_answer, lessons, step_confidence):
    gate_score_min = _safe_env_float("ACE_QG_GATE_SCORE_MIN", 0.60)
    lesson_score_min = _safe_env_float("ACE_QG_LESSON_SCORE_MIN", 0.55)
    overlap_min = _safe_env_float("ACE_QG_OVERLAP_MIN", 0.05)
    confidence_min = _safe_env_float("ACE_QG_CONFIDENCE_MIN", 0.70)
    max_accepted = _safe_env_int("ACE_QG_MAX_ACCEPTED_LESSONS", 4)

    accepted = []
    rejected = []
    for lesson in lessons:
        content = (lesson.get("content") or "").strip()
        if not content:
            rejected.append({"reason": "empty_content"})
            continue
        relevance = _lesson_relevance_score(question, content)
        lexical_overlap = _lesson_overlap_score(question, content)
        lesson_score = _lesson_quality_score(lesson)
        conf = _lesson_confidence_score(lesson, relevance, lesson_score, step_confidence)
        rejection_reasons = []
        if relevance < overlap_min:
            rejection_reasons.append("low_overlap")
        if lesson_score < lesson_score_min:
            rejection_reasons.append("low_quality")
        if conf < confidence_min:
            rejection_reasons.append("low_confidence")
        if rejection_reasons:
            rejected.append(
                {
                    "reason": ",".join(rejection_reasons),
                    "overlap_score": relevance,
                    "lexical_overlap_score": lexical_overlap,
                    "lesson_score": lesson_score,
                    "confidence_score": conf,
                }
            )
            continue
        lesson["quality_gate"] = {
            "overlap_score": relevance,
            "lexical_overlap_score": lexical_overlap,
            "lesson_score": lesson_score,
            "confidence_score": conf,
        }
        accepted.append((conf, lesson_score, relevance, lesson))

    accepted.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    accepted_lessons = [row[3] for row in accepted[:max_accepted]]

    accepted_quality_avg = sum(row[1] for row in accepted[:max_accepted]) / len(accepted_lessons) if accepted_lessons else 0.0
    accepted_conf_avg = sum(row[0] for row in accepted[:max_accepted]) / len(accepted_lessons) if accepted_lessons else 0.0
    accepted_relevance_avg = sum(row[2] for row in accepted[:max_accepted]) / len(accepted_lessons) if accepted_lessons else 0.0
    output_score = 1.0 if (model_answer or "").strip() else 0.0
    gate_score = 0.35 * output_score + 0.35 * accepted_quality_avg + 0.30 * accepted_conf_avg
    should_apply = bool(accepted_lessons) and gate_score >= gate_score_min

    return accepted_lessons, {
        "gate_score": gate_score,
        "should_apply_update": should_apply,
        "num_lessons_input": len(lessons),
        "num_lessons_accepted": len(accepted_lessons),
        "num_lessons_rejected": len(rejected),
        "accepted_relevance_avg": accepted_relevance_avg,
        "rejected_examples": rejected[:5],
    }


def _format_execution_trace(action_id, guidance, conversation_context, preprocessed_context, answer):
    sections = [f"Planner action: {action_id}"]
    if guidance:
        sections.append(guidance)
    if conversation_context:
        sections.append(conversation_context)
    if preprocessed_context:
        sections.append(f"=== Preprocessed Analysis ===\n{preprocessed_context}\n===")
    sections.append(f"Final answer:\n{answer}")
    return "\n\n".join(sections)


def _parse_json_response(content):
    normalized = (content or "").strip()
    if not normalized:
        return None
    if normalized.startswith("```"):
        parts = normalized.split("\n")
        if len(parts) > 2:
            normalized = "\n".join(parts[1:-1]).strip()
    try:
        return json.loads(normalized)
    except json.JSONDecodeError:
        match = JSON_OBJECT_PATTERN.search(normalized)
        if not match:
            return None
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return None


def _should_skip_reflection(answer):
    normalized = (answer or "").strip().lower()
    if not normalized:
        return True
    if "couldn't reach the ai service" in normalized:
        return True
    return hasattr(generate_reply_text, "mock_calls")


def _reflect_lessons(question, answer, trace):
    if not _safe_env_bool("ACE_REFLECTION_ENABLED", True):
        return []
    if _should_skip_reflection(answer):
        return []
    try:
        raw = generate_structured_text(
            REFLECTOR_PROMPT.format(
                trace=trace,
                question=question,
                model_answer=answer,
            ),
            system_instruction=REFLECTOR_SYSTEM_INSTRUCTION,
            max_output_tokens=_safe_env_int("ACE_REFLECTION_MAX_TOKENS", 700),
        )
    except Exception as exc:
        log_event("ace_reflector_failed", error_type=exc.__class__.__name__)
        return []

    payload = _parse_json_response(raw)
    if not isinstance(payload, dict):
        return []
    lessons = payload.get("lessons")
    return lessons if isinstance(lessons, list) else []


def _is_generic_lesson(content):
    normalized = (content or "").strip().lower()
    if not normalized:
        return True
    if len(_tokenize(normalized)) < 8:
        return True
    return any(pattern in normalized for pattern in GENERIC_LESSON_PATTERNS)


def _curate_lessons(lessons):
    curated = []
    seen = set()
    for lesson in lessons or []:
        content = re.sub(r"\s+", " ", str(lesson.get("content", "")).strip())
        if _is_generic_lesson(content):
            continue
        key = content.lower()
        if key in seen:
            continue
        seen.add(key)
        lesson_type = str(lesson.get("type", "")).strip().lower() or "success"
        tags = _normalize_tags(list(lesson.get("tags") or []) + [lesson_type])
        curated.append(
            {
                "content": content[:280],
                "type": lesson_type,
                "tags": tags or ["lesson"],
                "confidence": min(1.0, max(float(lesson.get("confidence", 0.78) or 0.78), 0.55)),
            }
        )
    return curated


def _looks_like_fact_recall(question):
    normalized = (question or "").strip().lower()
    return any(pattern in normalized for pattern in FACT_RECALL_PATTERNS)


def _extract_heuristic_lessons(question, answer):
    normalized_answer = (answer or "").strip()
    if not normalized_answer or _looks_like_fact_recall(question):
        return []

    lower_question = (question or "").lower()
    lower_answer = normalized_answer.lower()
    lessons = []

    procedural_markers = ["step", "first", "then", "finally", "next"]
    if "plan" in lower_question or "how should" in lower_question or any(marker in lower_answer for marker in procedural_markers):
        lessons.append(
            {
                "content": "For planning questions, respond with a short step-by-step sequence that starts with the goal and then lists concrete next actions.",
                "type": "success",
                "tags": ["planning", "procedural", "format"],
                "confidence": 0.82,
            }
        )

    if "recent conversation" in lower_answer or "context" in lower_answer:
        lessons.append(
            {
                "content": "When the answer depends on prior chat history, cite the recent conversation directly instead of guessing from general knowledge.",
                "type": "tool",
                "tags": ["context", "retrieval", "grounding"],
                "confidence": 0.76,
            }
        )

    return lessons


def _extract_lessons(question, answer, trace):
    reflected_lessons = _curate_lessons(_reflect_lessons(question, answer, trace))
    if reflected_lessons:
        return reflected_lessons, "reflector"
    return _extract_heuristic_lessons(question, answer), "heuristic"


def run_ace_chat_turn(session, user_text, preprocessed_context: str | None = None):
    profile = session.user
    learner_id = str(profile.user_id)
    context_scope_id = str(session.pk)
    log_event("ace_turn_start", session_id=session.pk, user_id=profile.user_id)
    memory_obj, _ = Memory.get_or_create_for_profile(profile)
    memory_obj.ensure_seed_bullets(learner_id=learner_id, seed_texts=META_STRATEGY_SEEDS)

    max_level = _safe_env_int("ACE_MAX_ACTION_LEVEL", 1)
    allowed_actions = ACTION_LEVELS[:max_level + 1]
    action_id = memory_obj.choose_planner_action(
        feature_text=user_text,
        actions=allowed_actions,
        epsilon=_safe_env_float("ACE_PLANNER_EPSILON", 0.03),
        ucb_c=_safe_env_float("ACE_PLANNER_UCB_C", 1.10),
        seed=_safe_env_int("ACE_PLANNER_SEED", 42),
    )
    log_event("ace_planner_selected", session_id=session.pk, action_id=action_id)
    bullets = memory_obj.retrieve_ranked_bullets(
        query=user_text,
        learner_id=learner_id,
        context_scope_id=context_scope_id,
        top_k=10,
        min_learned=_safe_env_int("ACE_MIN_LEARNED_BULLETS", 2),
        base_strength=_safe_env_float("ACE_MEMORY_BASE_STRENGTH", 100.0),
        relevance_w=_safe_env_float("ACE_WEIGHT_RELEVANCE", 0.60),
        strength_w=_safe_env_float("ACE_WEIGHT_STRENGTH", 0.20),
        type_w=_safe_env_float("ACE_WEIGHT_TYPE", 0.20),
        seed_penalty=_safe_env_float("ACE_SEED_BULLET_PENALTY", 0.25),
        learned_bonus=_safe_env_float("ACE_LEARNED_BULLET_BONUS", 0.08),
    )
    log_event("ace_memory_retrieved", session_id=session.pk, bullet_count=len(bullets))
    guidance = guidance_from_bullets(bullets)
    conversation_context = _build_recent_conversation_context(session)
    prompt_parts = []
    if guidance:
        prompt_parts.append(guidance)
    if conversation_context:
        prompt_parts.append(conversation_context)
    normalized_preprocessed_context = (preprocessed_context or "").strip()
    if normalized_preprocessed_context:
        prompt_parts.append(f"=== Preprocessed Analysis ===\n{normalized_preprocessed_context}\n===")
    prompt_parts.append(f"Latest user question:\n{user_text}")
    prompt_parts.append("Answer the latest user question while remaining consistent with the recent conversation.")
    base_prompt = "\n\n".join(prompt_parts)

    answer, step_confidence, recursion = _run_recursive_reasoning(
        question=user_text,
        base_prompt=base_prompt,
        action_id=action_id,
    )
    log_event(
        "ace_reasoning_completed",
        session_id=session.pk,
        improved=bool(recursion.get("improved")),
        rounds=recursion.get("rounds_planned"),
    )
    if not answer:
        answer = (generate_reply_text(user_text) or "").strip()
    if not answer:
        answer = "Sorry, I couldn't reach the AI service just now."

    trace = _format_execution_trace(
        action_id=action_id,
        guidance=guidance,
        conversation_context=conversation_context,
        preprocessed_context=normalized_preprocessed_context,
        answer=answer,
    )
    lessons, lesson_source = _extract_lessons(user_text, answer, trace)
    accepted_lessons, quality_gate = _apply_quality_gate(
        question=user_text,
        model_answer=answer,
        lessons=lessons,
        step_confidence=step_confidence,
    )
    quality_gate["lesson_source"] = lesson_source
    log_event(
        "ace_quality_gate",
        session_id=session.pk,
        should_apply=bool(quality_gate.get("should_apply_update")),
        accepted_lessons=quality_gate.get("num_lessons_accepted", 0),
        lesson_source=lesson_source,
    )
    ace_delta = {"num_new_bullets": 0, "num_updates": 0, "num_removals": 0}
    if quality_gate.get("should_apply_update"):
        ace_delta = memory_obj.apply_lessons(
            lessons=accepted_lessons,
            learner_id=learner_id,
            context_scope_id=context_scope_id,
        )
        log_event(
            "ace_memory_applied",
            session_id=session.pk,
            num_new_bullets=ace_delta.get("num_new_bullets", 0),
            num_updates=ace_delta.get("num_updates", 0),
            num_removals=ace_delta.get("num_removals", 0),
        )

    shaped = _compute_shaped_reward(
        step_score=step_confidence,
        output_valid=bool((answer or "").strip()),
        quality_gate_applied=bool(quality_gate.get("should_apply_update")),
        recursion_improved=bool(recursion.get("improved")),
        step_confidence=step_confidence or 0.7,
    )
    memory_obj.update_planner_reward(
        action_id=action_id,
        reward=shaped["final_reward"],
        confidence=shaped["confidence"],
    )
    log_event("ace_turn_done", session_id=session.pk, answer_len=len(answer or ""), action_id=action_id)

    return {
        "answer": answer,
        "planner": {"action_id": action_id},
        "quality_gate": quality_gate,
        "ace_delta": ace_delta,
        "recursion": recursion,
        "num_bullets_retrieved": len(bullets),
    }
