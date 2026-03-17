import re
from typing import Literal, Tuple

PromptClassification = Literal["simple", "complex"]

COMPLEXITY_THRESHOLD = 40

_STEP_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in [
    r"\bstep\s*\d",
    r"\bfirst\b",
    r"\b(?:second|third|fourth|fifth)\b",
    r"\bthen\b",
    r"\bnext\b",
    r"\bfinally\b",
    r"\b(?:afterward|lastly|subsequently)\b",
    r"\d+\.\s+\w",
    r"\b(?:if|when|unless)\b.*\b(?:then|else|instead|otherwise)\b",
])

_ANALYSIS_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in [
    r"\b(?:compare|contrast|tradeoffs?|pros\s+and\s+cons)\b",
    r"\b(?:evaluate|synthesize|assess)\b",
    r"\b(?:explain\s+why|walk\s+me\s+through|break\s+down|reason\s+about)\b",
    r"\b(?:step\s+by\s+step|help\s+me\s+plan)\b",
    r"\b(?:design|architect|implement|refactor)\b",
    r"\b(?:debug|diagnose|troubleshoot|root\s+cause)\b",
    r"\b(?:analyze|investigate|examine)\b",
])

_CONSTRAINT_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in [
    r"\b(?:must|shall|cannot|should\s+not|required|ensure)\b",
    r"\b(?:at\s+most|at\s+least|exactly|no\s+more\s+than|no\s+fewer\s+than)\b",
    r"\b(?:do\s+not|never|avoid|without|except)\b",
])

_CONJUNCTION_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in [
    r"\b(?:and\s+also|additionally|furthermore|moreover|in\s+addition)\b",
    r"\b(?:as\s+well\s+as|on\s+top\s+of\s+that|along\s+with)\b",
    r"\.\s+also\s+\b",
    r"\b(?:plus|meanwhile|separately)\b",
])

_ENUMERATION_PATTERN = re.compile(
    r"\b(?:list|give\s+me|name|provide|suggest|recommend)\s+\d+\b",
    re.IGNORECASE,
)


def _count_matches(text, patterns):
    return sum(1 for p in patterns if p.search(text))


def _score_length(word_count):
    if word_count >= 220:
        return 20
    if word_count >= 140:
        return 15
    if word_count >= 80:
        return 10
    if word_count >= 30:
        return 5
    return 0


def _score_multi_step(text):
    matches = _count_matches(text, _STEP_PATTERNS)
    if matches >= 4:
        return 25
    if matches >= 3:
        return 20
    if matches >= 2:
        return 15
    if matches >= 1:
        return 8
    return 0


def _score_analytical_depth(text):
    matches = _count_matches(text, _ANALYSIS_PATTERNS)
    if matches >= 3:
        return 20
    if matches >= 2:
        return 15
    if matches >= 1:
        return 8
    return 0


def _score_constraints(text):
    matches = _count_matches(text, _CONSTRAINT_PATTERNS)
    if matches >= 5:
        return 15
    if matches >= 3:
        return 10
    if matches >= 1:
        return 5
    return 0


def _score_question_density(text):
    count = text.count("?")
    if count >= 3:
        return 10
    if count >= 2:
        return 5
    return 0


def _score_conjunctions(text):
    matches = _count_matches(text, _CONJUNCTION_PATTERNS)
    if matches >= 2:
        return 10
    if matches >= 1:
        return 5
    return 0


def _score_enumeration(text):
    return 5 if _ENUMERATION_PATTERN.search(text) else 0


def _score_context_depth(message_count, has_any_signal):
    if message_count >= 15:
        return 5
    if message_count >= 8 and has_any_signal:
        return 3
    return 0


def compute_complexity_score(user_text, message_count=0):
    normalized = (user_text or "").strip()
    if not normalized:
        return 0

    word_count = len(normalized.split())

    length_score = _score_length(word_count)
    step_score = _score_multi_step(normalized)
    analysis_score = _score_analytical_depth(normalized)
    constraint_score = _score_constraints(normalized)
    question_score = _score_question_density(normalized)
    conjunction_score = _score_conjunctions(normalized)
    enumeration_score = _score_enumeration(normalized)

    has_any_signal = (step_score + analysis_score + constraint_score + question_score + conjunction_score + enumeration_score) > 0
    context_score = _score_context_depth(message_count, has_any_signal)

    active_dimensions = sum(1 for s in [step_score, analysis_score, constraint_score, question_score, conjunction_score, enumeration_score] if s > 0)
    synergy_bonus = 0
    if active_dimensions >= 3:
        synergy_bonus = 15
    elif active_dimensions >= 2:
        synergy_bonus = 10

    return min(
        length_score + step_score + analysis_score + constraint_score +
        question_score + conjunction_score + enumeration_score + context_score + synergy_bonus,
        100,
    )


def classify_prompt(user_text: str, message_count: int = 0) -> PromptClassification:
    score = compute_complexity_score(user_text, message_count)
    return "complex" if score >= COMPLEXITY_THRESHOLD else "simple"


def classify_prompt_with_score(user_text: str, message_count: int = 0) -> Tuple[PromptClassification, int]:
    score = compute_complexity_score(user_text, message_count)
    classification: PromptClassification = "complex" if score >= COMPLEXITY_THRESHOLD else "simple"
    return classification, score
