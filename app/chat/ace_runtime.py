import os
import re

from memoria.event_log import log_event
from app.services.gemini import generate_reply_text
from .models import Memory
from .models.memory_bullet import MemoryBullet
from .models.message import Role

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

PLANNER_ACTIONS = {
    "direct": {"rounds": 1, "candidates": 1},
    "explore": {"rounds": 1, "candidates": 2},
    "refine": {"rounds": 2, "candidates": 2},
    "deep_refine": {"rounds": 2, "candidates": 3},
}
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


def _tokenize(text):
    return TOKEN_PATTERN.findall((text or "").lower())


def _guidance_from_bullets(bullets):
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
    score = max(0.0, min(1.0, 0.55 * overlap + 0.25 * 1.0 + 0.20 * token_score))
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
        if round_idx > 0 and best_score >= 0.92:
            break

    recursion = {
        "rounds_planned": config["rounds"],
        "candidates_per_round": config["candidates"],
        "final_score": max(best_score, 0.0),
        "improved": config["rounds"] > 1,
    }
    return best_text, best_conf, recursion


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


def _apply_quality_gate(question, model_answer, lessons, step_confidence):
    gate_score_min = _safe_env_float("ACE_QG_GATE_SCORE_MIN", 0.60)
    lesson_score_min = _safe_env_float("ACE_QG_LESSON_SCORE_MIN", 0.55)
    overlap_min = _safe_env_float("ACE_QG_OVERLAP_MIN", 0.05)
    confidence_min = _safe_env_float("ACE_QG_CONFIDENCE_MIN", 0.70)
    max_accepted = _safe_env_int("ACE_QG_MAX_ACCEPTED_LESSONS", 4)

    accepted = []
    for lesson in lessons:
        content = (lesson.get("content") or "").strip()
        if not content:
            continue
        relevance = _lesson_relevance_score(question, content)
        lesson_score = _lesson_quality_score(lesson)
        conf = min(1.0, 0.45 * lesson_score + 0.40 * relevance + 0.15 * step_confidence)
        if relevance >= overlap_min and lesson_score >= lesson_score_min and conf >= confidence_min:
            lesson["quality_gate"] = {
                "overlap_score": relevance,
                "lesson_score": lesson_score,
                "confidence_score": conf,
            }
            accepted.append((conf, lesson_score, relevance, lesson))
    accepted.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    accepted_lessons = [row[3] for row in accepted[:max_accepted]]

    accepted_quality_avg = (
        sum(row[1] for row in accepted[:max_accepted]) / len(accepted_lessons) if accepted_lessons else 0.0
    )
    accepted_conf_avg = (
        sum(row[0] for row in accepted[:max_accepted]) / len(accepted_lessons) if accepted_lessons else 0.0
    )
    output_score = 1.0 if (model_answer or "").strip() else 0.0
    gate_score = 0.35 * output_score + 0.35 * accepted_quality_avg + 0.30 * accepted_conf_avg
    should_apply = bool(accepted_lessons) and gate_score >= gate_score_min
    return accepted_lessons, {
        "gate_score": gate_score,
        "should_apply_update": should_apply,
        "num_lessons_input": len(lessons),
        "num_lessons_accepted": len(accepted_lessons),
    }


def _extract_lessons(question, answer):
    answer = (answer or "").strip()
    if not answer:
        return []
    first_sentence = re.split(r"(?<=[.!?])\s+", answer)[0][:220]
    q_tokens = _tokenize(question)
    topic = " ".join(q_tokens[:6]) if q_tokens else "user_query"
    confidence = min(1.0, 0.55 + len(_tokenize(answer)) / 120.0)
    lessons = [{
        "content": f"When handling {topic}, provide a clear answer like: {first_sentence}",
        "type": "success",
        "tags": ["chat", "answering"],
        "confidence": confidence,
    }]
    if any(token in answer.lower() for token in ["step", "first", "then", "finally"]):
        lessons.append({
            "content": "For process questions, prefer structured step-by-step responses.",
            "type": "success",
            "tags": ["procedural", "format"],
            "confidence": 0.72,
        })
    return lessons


def run_ace_chat_turn(session, user_text):
    profile = session.user
    learner_id = str(profile.user_id)
    context_scope_id = str(session.pk)
    log_event("ace_turn_start", session_id=session.pk, user_id=profile.user_id)
    memory_obj, _ = Memory.get_or_create_for_profile(profile)
    memory_obj.ensure_seed_bullets(learner_id=learner_id, seed_texts=META_STRATEGY_SEEDS)

    action_id = memory_obj.choose_planner_action(
        feature_text=user_text,
        actions=list(PLANNER_ACTIONS.keys()),
        epsilon=_safe_env_float("ACE_PLANNER_EPSILON", 0.08),
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
    guidance = _guidance_from_bullets(bullets)
    conversation_context = _build_recent_conversation_context(session)
    prompt_parts = []
    if guidance:
        prompt_parts.append(guidance)
    if conversation_context:
        prompt_parts.append(conversation_context)
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

    lessons = _extract_lessons(user_text, answer)
    accepted_lessons, quality_gate = _apply_quality_gate(
        question=user_text,
        model_answer=answer,
        lessons=lessons,
        step_confidence=step_confidence,
    )
    log_event(
        "ace_quality_gate",
        session_id=session.pk,
        should_apply=bool(quality_gate.get("should_apply_update")),
        accepted_lessons=quality_gate.get("num_lessons_accepted", 0),
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

    reward = (
        0.55 * max(0.0, min(1.0, step_confidence))
        + 0.20 * (1.0 if answer.strip() else 0.0)
        + 0.15 * (1.0 if quality_gate.get("should_apply_update") else 0.0)
        + 0.10 * (1.0 if recursion.get("improved") else 0.0)
    )
    memory_obj.update_planner_reward(action_id=action_id, reward=reward, confidence=step_confidence or 0.7)
    log_event("ace_turn_done", session_id=session.pk, answer_len=len(answer or ""), action_id=action_id)

    return {
        "answer": answer,
        "planner": {"action_id": action_id},
        "quality_gate": quality_gate,
        "ace_delta": ace_delta,
        "recursion": recursion,
        "num_bullets_retrieved": len(bullets),
    }
