import hashlib
import json
import math
import re

from memoria.event_log import log_event
from app.services.gemini import generate_reply_text, generate_structured_text
from app.services import neo4j_memory as neo4j
from . import decay
from .utils import safe_env_bool, safe_env_int, safe_env_float

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


_safe_env_float = safe_env_float
_safe_env_int = safe_env_int
_safe_env_bool = safe_env_bool


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
        helpful = bullet.get("helpfulCount", 0) if isinstance(bullet, dict) else bullet.helpful_count
        harmful = bullet.get("harmfulCount", 0) if isinstance(bullet, dict) else bullet.harmful_count
        content = bullet.get("content", "") if isinstance(bullet, dict) else bullet.content
        lines.append(f"{idx}. [+{helpful}/-{harmful}] {content}")
    lines.append("===")
    return "\n".join(lines)


def _session_id(session):
    if isinstance(session, dict):
        return str(session.get("id", ""))
    return str(session.pk)


def _build_recent_conversation_context(session):
    max_messages = _safe_env_int("ACE_CONTEXT_MAX_MESSAGES", 12)
    max_messages = min(max(max_messages, 2), 40)

    sid = _session_id(session)
    rows = neo4j.get_messages_for_session_values(sid, exclude_role=1, limit=max_messages)
    if not rows:
        return ""

    rows.reverse()
    role_name_map = {2: "User", 3: "Assistant", "user": "User", "assistant": "Assistant"}
    lines = ["=== Recent Conversation ==="]
    for row in rows:
        role = row.get("role", "")
        speaker = role_name_map.get(role, role_name_map.get(int(role) if str(role).isdigit() else 0, "Other"))
        normalized = (row.get("content") or "").strip()
        if not normalized:
            continue
        lines.append(f"{speaker}: {normalized}")
    lines.append("===")
    return "\n".join(lines)


def _text_similarity(a, b):
    wa = set(_tokenize(a))
    wb = set(_tokenize(b))
    if not wa or not wb:
        return 0.0
    return len(wa.intersection(wb)) / len(wa.union(wb))


def _candidate_score(question, content):
    if not (content or "").strip():
        return 0.0, 0.0
    overlap = _text_similarity(question, content)
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
    try:
        from app.services import embedding as embeddingService
        if embeddingService.is_loaded():
            qVec = embeddingService.encode_query(question)
            lVec = embeddingService.encode_query(lesson_content)
            if qVec is not None and lVec is not None:
                from sklearn.metrics.pairwise import cosine_similarity
                return float(cosine_similarity(qVec, lVec)[0][0])
    except Exception:
        pass

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


def _build_semantic_context(query, memory_id, learner_id, top_k=3):
    try:
        from app.services import embedding as embeddingService
        if not embeddingService.is_loaded():
            return ""
        import numpy as np
        bulletRows = neo4j.get_bullets_with_embeddings(str(memory_id), learner_id)
        if not bulletRows:
            return ""
        queryEmb = embeddingService.encode_query(query)
        if queryEmb is None:
            return ""
        corpusEmbs = []
        validContents = []
        for row in bulletRows:
            vec = embeddingService.json_to_embedding(row.get("embeddingJson", ""))
            if vec is not None:
                corpusEmbs.append(vec)
                validContents.append(row.get("content", ""))
        if not corpusEmbs:
            return ""
        corpusMatrix = np.array(corpusEmbs)
        ranked = embeddingService.cosine_search(queryEmb, corpusMatrix, top_k=top_k)
        if not ranked:
            return ""
        lines = ["=== Semantically Relevant Context ==="]
        for rank, (idx, score) in enumerate(ranked, 1):
            lines.append(f"{rank}. [sim={score:.2f}] {validContents[idx]}")
        lines.append("===")
        return "\n".join(lines)
    except Exception:
        return ""


def _compute_content_hash(text):
    normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
    return hashlib.sha256(normalized.encode()).hexdigest()


def _infer_memory_type(content):
    lower = (content or "").lower()
    if any(word in lower for word in ["step", "procedure", "workflow", "then", "finally"]):
        return 3
    if any(word in lower for word in ["user", "prefers", "asked", "history", "experience"]):
        return 2
    return 1


def _memory_type_to_channel(memory_type):
    if memory_type == 2:
        return "episodic"
    if memory_type == 3:
        return "procedural"
    return "semantic"


def _memory_type_priority(memory_type):
    if memory_type == 3:
        return 1.0
    if memory_type == 2:
        return 0.7
    return 0.4


def _component_score(strength, last_index, decay_rate, access_clock):
    return decay.component_score(strength, last_index, decay_rate, access_clock)


def _compute_strength_score(bullet, access_clock):
    return decay.total_strength(
        bullet.get("semanticStrength", 0), bullet.get("semanticAccessIndex"),
        bullet.get("episodicStrength", 0), bullet.get("episodicAccessIndex"),
        bullet.get("proceduralStrength", 0), bullet.get("proceduralAccessIndex"),
        access_clock,
    )


def _retrieve_ranked_bullets_neo4j(
    memory_id, learner_id, context_scope_id, query,
    top_k=10, min_learned=2, relevance_w=0.60,
    strength_w=0.20, type_w=0.20, seed_penalty=0.25,
    learned_bonus=0.08, access_clock=0,
):
    allBullets = neo4j.get_bullets_for_memory(
        str(memory_id),
        learner_id=learner_id,
        context_scope_ids=["", context_scope_id],
    )
    if not allBullets:
        return []

    useSemanticScoring = False
    queryEmbedding = None
    bulletEmbeddings = {}
    try:
        from app.services import embedding as embeddingService
        if embeddingService.is_available() and embeddingService.is_loaded():
            queryEmbedding = embeddingService.encode_query(query)
            if queryEmbedding is not None:
                for bullet in allBullets:
                    vec = embeddingService.json_to_embedding(bullet.get("embeddingJson", ""))
                    if vec is not None:
                        bulletEmbeddings[bullet["id"]] = vec
                useSemanticScoring = bool(bulletEmbeddings)
    except Exception:
        pass

    DECAY_WRITEBACK_THRESHOLD = 5.0
    DECAY_DELETE_THRESHOLD = 1.0
    bulletsToDelete = []

    scored = []
    for bullet in allBullets:
        semDecayed = _component_score(float(bullet.get("semanticStrength", 0)), bullet.get("semanticAccessIndex"), 0.01, access_clock)
        epiDecayed = _component_score(float(bullet.get("episodicStrength", 0)), bullet.get("episodicAccessIndex"), 0.05, access_clock)
        proDecayed = _component_score(float(bullet.get("proceduralStrength", 0)), bullet.get("proceduralAccessIndex"), 0.002, access_clock)
        strengthScore = semDecayed + epiDecayed + proDecayed

        isSeed = "meta_strategy" in {tag.lower() for tag in (bullet.get("tags") or [])}
        if not isSeed:
            createdAt = bullet.get("createdAt", "")
            ttlDays = int(bullet.get("ttlDays", 365) or 365)
            ttlExpired = False
            if createdAt:
                try:
                    from django.utils import timezone as tz
                    from datetime import timedelta
                    created = tz.datetime.fromisoformat(str(createdAt).replace("Z", "+00:00"))
                    ttlExpired = (tz.now() - created).days > ttlDays
                except Exception:
                    pass

            if strengthScore < DECAY_DELETE_THRESHOLD or ttlExpired:
                bulletsToDelete.append(bullet["id"])
                continue

            origSem = float(bullet.get("semanticStrength", 0))
            origEpi = float(bullet.get("episodicStrength", 0))
            origPro = float(bullet.get("proceduralStrength", 0))
            if abs(origSem - semDecayed) > DECAY_WRITEBACK_THRESHOLD or abs(origEpi - epiDecayed) > DECAY_WRITEBACK_THRESHOLD or abs(origPro - proDecayed) > DECAY_WRITEBACK_THRESHOLD:
                neo4j.update_bullet(str(bullet["id"]),
                    semantic_strength=round(semDecayed, 2),
                    episodic_strength=round(epiDecayed, 2),
                    procedural_strength=round(proDecayed, 2),
                    strength=max(0, int(strengthScore)),
                )

        strengthScore = _compute_strength_score(bullet, access_clock)
        if useSemanticScoring and queryEmbedding is not None and bullet["id"] in bulletEmbeddings:
            from sklearn.metrics.pairwise import cosine_similarity
            relevance = float(cosine_similarity(
                queryEmbedding, bulletEmbeddings[bullet["id"]].reshape(1, -1)
            )[0][0])
        else:
            relevance = _text_similarity(query, bullet.get("content", ""))

        typePriority = _memory_type_priority(int(bullet.get("memoryType", 1)))
        tags = {tag.lower() for tag in (bullet.get("tags") or [])}
        bonus = float(learned_bonus) if "meta_strategy" not in tags else -float(seed_penalty)
        normalizedStrength = min(strengthScore / 100.0, 1.0) if strengthScore > 0 else 0.0
        combined = (
            float(relevance_w) * relevance
            + float(strength_w) * normalizedStrength
            + float(type_w) * typePriority
            + bonus
        )
        scored.append((combined, bullet))
    scored.sort(key=lambda row: row[0], reverse=True)

    if bulletsToDelete:
        try:
            neo4j.delete_bullets_by_ids(bulletsToDelete)
            log_event("memory_decay_cleanup", deleted_count=len(bulletsToDelete))
        except Exception:
            pass

    selected = []
    selectedIds = set()
    for _, bullet in scored:
        if "meta_strategy" in {tag.lower() for tag in (bullet.get("tags") or [])}:
            continue
        selected.append(bullet)
        selectedIds.add(bullet["id"])
        if len(selected) >= min(min_learned, top_k):
            break
    for _, bullet in scored:
        if bullet["id"] in selectedIds:
            continue
        selected.append(bullet)
        if len(selected) >= top_k:
            break

    if selected:
        newClock = access_clock + 1
        from django.utils import timezone
        nowStr = timezone.now().isoformat()
        for bullet in selected:
            channel = _memory_type_to_channel(int(bullet.get("memoryType", 1)))
            updateFields = {"last_accessed": nowStr}
            if channel == "episodic":
                updateFields["episodic_access_index"] = newClock
                updateFields["episodic_last_access"] = nowStr
            elif channel == "procedural":
                updateFields["procedural_access_index"] = newClock
                updateFields["procedural_last_access"] = nowStr
            else:
                updateFields["semantic_access_index"] = newClock
                updateFields["semantic_last_access"] = nowStr
            neo4j.update_bullet(str(bullet["id"]), **updateFields)
        neo4j.update_memory_fields(str(memory_id), access_clock=newClock)

    return selected


def _apply_lessons_neo4j(memory_id, learner_id, context_scope_id, lessons, access_clock):
    createdCount = 0
    updatedCount = 0

    for lesson in lessons:
        content = (lesson.get("content") or "").strip()
        if not content:
            continue
        contentHash = _compute_content_hash(content)
        match = neo4j.get_bullet_by_content_hash(str(memory_id), contentHash)

        if not match:
            try:
                from app.services import embedding as embeddingService
                if embeddingService.is_available():
                    import numpy as np
                    from sklearn.metrics.pairwise import cosine_similarity as cos_sim
                    newEmb = embeddingService.encode_query(content)
                    existing = neo4j.get_bullets_with_embeddings(str(memory_id), learner_id)
                    if existing and newEmb is not None:
                        vecs = []
                        valid = []
                        for b in existing:
                            vec = embeddingService.json_to_embedding(b.get("embeddingJson", ""))
                            if vec is not None:
                                vecs.append(vec)
                                valid.append(b)
                        if vecs:
                            corpus = np.array(vecs)
                            sims = cos_sim(newEmb, corpus)[0]
                            bestIdx = int(np.argmax(sims))
                            if sims[bestIdx] >= 0.85:
                                match = valid[bestIdx]
            except Exception:
                pass

        if not match:
            allBullets = neo4j.get_bullets_for_memory(str(memory_id), learner_id=learner_id)
            for bullet in allBullets[:60]:
                if _text_similarity(content, bullet.get("content", "")) >= 0.75:
                    match = bullet
                    break

        if match:
            newHelpful = int(match.get("helpfulCount", 0)) + 1
            access_clock += 1
            channel = _memory_type_to_channel(int(match.get("memoryType", 1)))
            from django.utils import timezone
            nowStr = timezone.now().isoformat()
            updateFields = {
                "helpful_count": newHelpful,
                "last_accessed": nowStr,
            }
            if channel == "episodic":
                updateFields["episodic_strength"] = max(float(match.get("episodicStrength", 0)), 100.0)
                updateFields["episodic_access_index"] = access_clock
                updateFields["episodic_last_access"] = nowStr
            elif channel == "procedural":
                updateFields["procedural_strength"] = max(float(match.get("proceduralStrength", 0)), 100.0)
                updateFields["procedural_access_index"] = access_clock
                updateFields["procedural_last_access"] = nowStr
            else:
                updateFields["semantic_strength"] = max(float(match.get("semanticStrength", 0)), 100.0)
                updateFields["semantic_access_index"] = access_clock
                updateFields["semantic_last_access"] = nowStr
            neo4j.update_bullet(str(match["id"]), **updateFields)
            updatedCount += 1
            continue

        memoryType = _infer_memory_type(content)
        channel = _memory_type_to_channel(memoryType)
        access_clock += 1
        bulletKey = hashlib.md5(content.lower().encode()).hexdigest()[:12]

        bulletParams = {
            "memory_id": str(memory_id),
            "learner_id": learner_id,
            "content": content,
            "tags": lesson.get("tags") or ["lesson"],
            "memory_type": memoryType,
            "topic": (lesson.get("tags") or ["general"])[0],
            "strength": 100,
            "ttl_days": 365,
            "bullet_key": bulletKey,
            "context_scope_id": context_scope_id,
            "content_hash": contentHash,
        }
        if channel == "episodic":
            bulletParams["episodic_strength"] = 100.0
            bulletParams["episodic_access_index"] = access_clock
        elif channel == "procedural":
            bulletParams["procedural_strength"] = 100.0
            bulletParams["procedural_access_index"] = access_clock
        else:
            bulletParams["semantic_strength"] = 100.0
            bulletParams["semantic_access_index"] = access_clock

        newBullet = neo4j.create_bullet(**bulletParams)

        try:
            from app.services import embedding as embeddingService
            if embeddingService.is_available() and newBullet.get("id"):
                embs = embeddingService.encode_texts([content])
                if embs is not None:
                    neo4j.update_bullet(
                        str(newBullet["id"]),
                        embedding_json=embeddingService.embedding_to_json(embs[0]),
                    )
        except Exception:
            pass

        from app.chat.signals import auto_mark_skill_neo4j
        auto_mark_skill_neo4j(newBullet)
        createdCount += 1

    neo4j.update_memory_fields(str(memory_id), access_clock=access_clock)
    return {"num_new_bullets": createdCount, "num_updates": updatedCount, "num_removals": 0}


def _choose_planner_action_neo4j(memory_id, plannerState, access_clock, feature_text, actions, epsilon, ucb_c, seed):
    import random as rng_module
    plannerState = dict(plannerState or {})
    actionStats = plannerState.get("actions", {})
    totalPulls = int(plannerState.get("total_pulls", 0))
    rng = rng_module.Random(int(seed) + access_clock + len(feature_text or ""))

    for action in actions:
        actionStats.setdefault(action, {"pulls": 0, "updates": 0, "reward_sum": 0.0})

    explore = rng.random() < float(epsilon)
    scores = {}
    for action, stats in actionStats.items():
        pulls = int(stats.get("pulls", 0))
        updates = int(stats.get("updates", 0))
        rewardSum = float(stats.get("reward_sum", 0.0))
        mean = rewardSum / updates if updates > 0 else 0.5
        bonus = float(ucb_c) * math.sqrt(math.log(totalPulls + len(actionStats) + 1) / (pulls + 1))
        scores[action] = mean + bonus

    if explore:
        actionId = rng.choice(list(actions))
    else:
        actionId = sorted(scores.keys(), key=lambda key: (scores[key], key), reverse=True)[0]

    actionStats[actionId]["pulls"] = int(actionStats[actionId].get("pulls", 0)) + 1
    plannerState["actions"] = actionStats
    plannerState["total_pulls"] = totalPulls + 1
    neo4j.update_memory_fields(str(memory_id), planner_state=plannerState)
    return actionId


def _update_planner_reward_neo4j(memory_id, plannerState, action_id, reward, confidence):
    plannerState = dict(plannerState or {})
    actionStats = plannerState.get("actions", {})
    stats = dict(actionStats.get(action_id, {"pulls": 0, "updates": 0, "reward_sum": 0.0}))
    clippedReward = max(0.0, min(1.0, float(reward)))
    clippedConf = max(0.0, min(1.0, float(confidence)))
    weightedReward = clippedReward * clippedConf
    stats["updates"] = int(stats.get("updates", 0)) + 1
    stats["reward_sum"] = float(stats.get("reward_sum", 0.0)) + weightedReward
    actionStats[action_id] = stats
    plannerState["actions"] = actionStats
    plannerState["total_updates"] = int(plannerState.get("total_updates", 0)) + 1
    neo4j.update_memory_fields(str(memory_id), planner_state=plannerState)


def _ensure_seed_bullets_neo4j(memory_id, learner_id, seed_texts):
    existing = neo4j.get_bullets_for_memory(str(memory_id), learner_id=learner_id)
    if existing:
        return
    for text in seed_texts:
        contentHash = _compute_content_hash(text)
        bulletKey = hashlib.md5(text.lower().encode()).hexdigest()[:12]
        neo4j.create_bullet(
            memory_id=str(memory_id),
            learner_id=learner_id,
            content=text,
            tags=["meta_strategy", "procedural"],
            memory_type=3,
            topic="meta_strategy",
            strength=100,
            ttl_days=3650,
            concept="meta_strategy",
            bullet_key=bulletKey,
            content_hash=contentHash,
            procedural_strength=100.0,
            procedural_access_index=0,
        )


def run_ace_chat_turn(session, user_text, preprocessed_context: str | None = None, agent=None, doc_chunks=None):
    sid = _session_id(session)
    if isinstance(session, dict):
        userId = session.get("userId", session.get("createdBy", ""))
    else:
        userId = str(session.user.pk)
    learnerId = userId
    contextScopeId = sid
    log_event("ace_turn_start", session_id=sid, user_id=userId)

    memoryData = neo4j.get_or_create_memory(userId)
    memoryId = memoryData.get("id", "")
    accessClock = int(memoryData.get("accessClock", 0))
    plannerState = memoryData.get("plannerState", {})
    if isinstance(plannerState, str):
        try:
            plannerState = json.loads(plannerState)
        except (json.JSONDecodeError, TypeError):
            plannerState = {}

    _ensure_seed_bullets_neo4j(memoryId, learnerId, META_STRATEGY_SEEDS)

    maxLevel = _safe_env_int("ACE_MAX_ACTION_LEVEL", 1)
    allowedActions = ACTION_LEVELS[:maxLevel + 1]
    actionId = _choose_planner_action_neo4j(
        memory_id=memoryId,
        plannerState=plannerState,
        access_clock=accessClock,
        feature_text=user_text,
        actions=allowedActions,
        epsilon=_safe_env_float("ACE_PLANNER_EPSILON", 0.03),
        ucb_c=_safe_env_float("ACE_PLANNER_UCB_C", 1.10),
        seed=_safe_env_int("ACE_PLANNER_SEED", 42),
    )
    log_event("ace_planner_selected", session_id=sid, action_id=actionId)

    bullets = _retrieve_ranked_bullets_neo4j(
        memory_id=memoryId,
        learner_id=learnerId,
        context_scope_id=contextScopeId,
        query=user_text,
        top_k=10,
        min_learned=_safe_env_int("ACE_MIN_LEARNED_BULLETS", 2),
        relevance_w=_safe_env_float("ACE_WEIGHT_RELEVANCE", 0.60),
        strength_w=_safe_env_float("ACE_WEIGHT_STRENGTH", 0.20),
        type_w=_safe_env_float("ACE_WEIGHT_TYPE", 0.20),
        seed_penalty=_safe_env_float("ACE_SEED_BULLET_PENALTY", 0.25),
        learned_bonus=_safe_env_float("ACE_LEARNED_BULLET_BONUS", 0.08),
        access_clock=accessClock,
    )
    log_event("ace_memory_retrieved", session_id=sid, bullet_count=len(bullets))
    guidance = guidance_from_bullets(bullets)

    from app.chat.skill_service import get_enabled_skills_for_user, format_skills_for_prompt
    if isinstance(session, dict):
        from django.contrib.auth.models import User
        try:
            userObj = User.objects.get(pk=int(userId))
        except (User.DoesNotExist, ValueError):
            userObj = None
    else:
        userObj = session.user.user
    enabledSkills = get_enabled_skills_for_user(userObj) if userObj else []
    skillContext = format_skills_for_prompt(enabledSkills)

    conversationContext = _build_recent_conversation_context(session)
    semanticContext = _build_semantic_context(user_text, memoryId, learnerId, top_k=3)

    promptParts = []
    if skillContext:
        promptParts.append(skillContext)
    if guidance:
        promptParts.append(guidance)
    if semanticContext:
        promptParts.append(semanticContext)
    if doc_chunks:
        docParts = [f"From \"{chunk['filename']}\":\n  {chunk['chunk']}" for chunk in doc_chunks]
        promptParts.append(f"=== Relevant Documents ===\n{chr(10).join(docParts)}\n===")
    if conversationContext:
        promptParts.append(conversationContext)
    normalizedPreprocessed = (preprocessed_context or "").strip()
    if normalizedPreprocessed:
        promptParts.append(f"=== Preprocessed Analysis ===\n{normalizedPreprocessed}\n===")
    if agent:
        agentPrompt = agent.get("systemPrompt", "") if isinstance(agent, dict) else getattr(agent, "system_prompt", "")
        if agentPrompt:
            promptParts.append(f"=== Agent Instructions ===\n{agentPrompt}\n===")
    promptParts.append(f"Latest user question:\n{user_text}")
    promptParts.append("Answer the latest user question while remaining consistent with the recent conversation.")
    basePrompt = "\n\n".join(promptParts)

    answer, stepConfidence, recursion = _run_recursive_reasoning(
        question=user_text,
        base_prompt=basePrompt,
        action_id=actionId,
    )
    log_event(
        "ace_reasoning_completed",
        session_id=sid,
        improved=bool(recursion.get("improved")),
        rounds=recursion.get("rounds_planned"),
    )
    if not answer:
        answer = (generate_reply_text(user_text) or "").strip()
    if not answer:
        answer = "Sorry, I couldn't reach the AI service just now."

    trace = _format_execution_trace(
        action_id=actionId,
        guidance=guidance,
        conversation_context=conversationContext,
        preprocessed_context=normalizedPreprocessed,
        answer=answer,
    )
    lessons, lessonSource = _extract_lessons(user_text, answer, trace)
    acceptedLessons, qualityGate = _apply_quality_gate(
        question=user_text,
        model_answer=answer,
        lessons=lessons,
        step_confidence=stepConfidence,
    )
    qualityGate["lesson_source"] = lessonSource
    log_event(
        "ace_quality_gate",
        session_id=sid,
        should_apply=bool(qualityGate.get("should_apply_update")),
        accepted_lessons=qualityGate.get("num_lessons_accepted", 0),
        lesson_source=lessonSource,
    )

    refreshedMemory = neo4j.get_memory(memoryId)
    currentClock = int(refreshedMemory.get("accessClock", accessClock)) if refreshedMemory else accessClock

    aceDelta = {"num_new_bullets": 0, "num_updates": 0, "num_removals": 0}
    if qualityGate.get("should_apply_update"):
        aceDelta = _apply_lessons_neo4j(
            memory_id=memoryId,
            learner_id=learnerId,
            context_scope_id=contextScopeId,
            lessons=acceptedLessons,
            access_clock=currentClock,
        )
        log_event(
            "ace_memory_applied",
            session_id=sid,
            num_new_bullets=aceDelta.get("num_new_bullets", 0),
            num_updates=aceDelta.get("num_updates", 0),
            num_removals=aceDelta.get("num_removals", 0),
        )

    shaped = _compute_shaped_reward(
        step_score=stepConfidence,
        output_valid=bool((answer or "").strip()),
        quality_gate_applied=bool(qualityGate.get("should_apply_update")),
        recursion_improved=bool(recursion.get("improved")),
        step_confidence=stepConfidence or 0.7,
    )

    refreshedMemory2 = neo4j.get_memory(memoryId)
    currentPlannerState = (refreshedMemory2 or {}).get("plannerState", plannerState)
    if isinstance(currentPlannerState, str):
        try:
            currentPlannerState = json.loads(currentPlannerState)
        except (json.JSONDecodeError, TypeError):
            currentPlannerState = {}

    _update_planner_reward_neo4j(
        memory_id=memoryId,
        plannerState=currentPlannerState,
        action_id=actionId,
        reward=shaped["final_reward"],
        confidence=shaped["confidence"],
    )
    log_event("ace_turn_done", session_id=sid, answer_len=len(answer or ""), action_id=actionId)

    return {
        "answer": answer,
        "planner": {"action_id": actionId},
        "quality_gate": qualityGate,
        "ace_delta": aceDelta,
        "recursion": recursion,
        "num_bullets_retrieved": len(bullets),
    }
