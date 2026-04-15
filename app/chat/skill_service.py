import json
import re

from django.utils.text import slugify

from app.services.gemini import generate_structured_text
from app.services import neo4j_memory as neo4j

MEMORY_TYPE_LABELS = {1: "Semantic", 2: "Episodic", 3: "Procedural"}

SKILL_GENERATION_SYSTEM_PROMPT = (
    "You are a skill architect for an AI assistant. Your job is to analyze a cluster of "
    "related memory bullets (things the user frequently needs help with) and synthesize them "
    "into a structured, reusable skill document.\n\n"
    "A skill is a set of expert instructions that guides the AI when a specific type of task "
    "is detected. Think of it like a SKILL.md file in Claude Code.\n\n"
    "Output ONLY valid JSON with these fields:\n"
    '  "name": short skill name (2-5 words, e.g., "Professional Email Writer")\n'
    '  "description": one sentence describing when this skill should activate\n'
    '  "category": one of: writing, communication, research, project-management, '
    "document-processing, data-analysis, strategy, knowledge-management, general\n"
    '  "content": the full skill instructions in markdown with ## sections for Process, '
    "Rules, and Examples. Keep under 300 words.\n\n"
    "The skill content should be actionable instructions the AI follows, not a description of "
    "what the skill does. Write in imperative mood (\"Do X\", \"Always Y\", \"Never Z\")."
)

MIN_BULLET_SCORE = 3
MIN_BULLETS_FOR_SKILL = 2
MAX_SKILLS_PER_GENERATION = 5


def _get_profile(user):
    from .utils import get_or_create_profile
    return get_or_create_profile(user)


def _cluster_bullets_by_topic(bullets):
    clusters = {}
    for bullet in bullets:
        topic = (bullet.get("topic") or "general").strip().lower()
        if topic not in clusters:
            clusters[topic] = []
        clusters[topic].append(bullet)
    return {k: v for k, v in clusters.items() if len(v) >= MIN_BULLETS_FOR_SKILL}


def _format_bullets_for_prompt(bullets):
    lines = []
    for bullet in bullets:
        score = bullet.get("helpfulCount", 0) - bullet.get("harmfulCount", 0)
        memoryType = MEMORY_TYPE_LABELS.get(bullet.get("memoryType", 1), "Semantic")
        lines.append(f"- [{memoryType}] (score: {score}) {bullet.get('content', '')}")
    return "\n".join(lines)


def generate_skill_from_bullets(user, bullets, topic="general"):
    profile = _get_profile(user)
    bulletText = _format_bullets_for_prompt(bullets)
    prompt = (
        f"Analyze these high-scoring memory bullets about \"{topic}\" and create a skill:\n\n"
        f"{bulletText}\n\n"
        "Generate a structured skill that captures the reusable patterns from these memories. "
        "Output ONLY valid JSON."
    )

    try:
        rawResponse = generate_structured_text(
            prompt,
            system_instruction=SKILL_GENERATION_SYSTEM_PROMPT,
            max_output_tokens=1024,
            thinking_level="low",
        )
    except Exception:
        return None

    jsonText = rawResponse.strip()
    if jsonText.startswith("```"):
        jsonText = re.sub(r"^```(?:json)?\s*", "", jsonText)
        jsonText = re.sub(r"\s*```$", "", jsonText)

    try:
        data = json.loads(jsonText)
    except (json.JSONDecodeError, ValueError):
        return None

    name = data.get("name", "").strip()
    if not name:
        return None

    bulletIds = [b.get("id", "") for b in bullets]
    slugifiedName = slugify(name)[:120] or "skill"

    skill = neo4j.create_skill(
        user_id=str(profile.pk),
        name=name,
        slug=slugifiedName,
        description=data.get("description", ""),
        content=data.get("content", ""),
        category=data.get("category", "general"),
        source="generated",
        source_bullet_ids=bulletIds,
    )
    return skill


def auto_generate_skills_for_user(user):
    profile = _get_profile(user)

    memory = neo4j.get_or_create_memory(str(profile.pk))
    allBullets = neo4j.get_bullets_for_memory(memory["id"], learner_id=str(profile.pk))

    filtered = [
        b for b in allBullets
        if (b.get("topic") or "").strip().lower() != "meta_strategy"
    ]
    filtered.sort(key=lambda b: (-b.get("helpfulCount", 0), -b.get("strength", 0)))

    qualifiedBullets = [
        b for b in filtered
        if (b.get("helpfulCount", 0) - b.get("harmfulCount", 0)) >= MIN_BULLET_SCORE
    ]

    if not qualifiedBullets:
        return []

    clusters = _cluster_bullets_by_topic(qualifiedBullets)
    existingSkills = neo4j.get_skills_for_user(str(profile.pk))
    existingSlugs = set(s.get("slug", "") for s in existingSkills)
    generatedSkills = []

    for topic, bullets in list(clusters.items())[:MAX_SKILLS_PER_GENERATION]:
        candidateSlug = slugify(topic)[:120] or "skill"
        if candidateSlug in existingSlugs:
            continue

        skill = generate_skill_from_bullets(user, bullets[:8], topic=topic)
        if skill:
            generatedSkills.append(skill)
            existingSlugs.add(skill.get("slug", ""))

    return generatedSkills


def install_template_skill(user, templateData):
    profile = _get_profile(user)

    skill = neo4j.create_skill(
        user_id=str(profile.pk),
        name=templateData["name"],
        slug=slugify(templateData["name"])[:120] or "skill",
        description=templateData["description"],
        content=templateData["content"],
        category=templateData.get("category", "general"),
        source="template",
    )
    return skill


def get_enabled_skills_for_user(user):
    profile = _get_profile(user)
    return neo4j.get_skills_for_user(str(profile.pk), enabled_only=True)


def format_skills_for_prompt(skills):
    if not skills:
        return ""

    parts = ["=== Active Skills ==="]
    for skill in skills:
        parts.append(f"\n## Skill: {skill.get('name', '')}")
        description = skill.get("description", "")
        if description:
            parts.append(f"When to use: {description}")
        parts.append(f"\n{skill.get('content', '')}")
    parts.append("\n===")
    return "\n".join(parts)
