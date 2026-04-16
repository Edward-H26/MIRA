import logging
import re

from django.http import Http404

from app.services import neo4j_memory as neo4j
from .utils import get_or_create_profile

logger = logging.getLogger(__name__)


class _AttrDict(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


def _get_profile(user):
    return get_or_create_profile(user)


def _agent_to_dict(agent: dict, includeOwner: bool = False) -> dict:
    result = {
        "id": str(agent.get("id", "")),
        "name": agent.get("name", ""),
        "description": agent.get("description", ""),
        "systemPrompt": agent.get("systemPrompt", ""),
        "temperature": float(agent.get("temperature", 0.7)),
        "maxTokens": agent.get("maxTokens", 1024),
        "isActive": agent.get("isActive", True),
        "is_active": agent.get("isActive", True),
        "configuration": agent.get("configuration", {}),
        "createdAt": agent.get("createdAt", ""),
        "updatedAt": agent.get("updatedAt", ""),
    }
    if isinstance(result["configuration"], str):
        import json
        try:
            result["configuration"] = json.loads(result["configuration"])
        except (json.JSONDecodeError, TypeError):
            result["configuration"] = {}
    if includeOwner and agent.get("ownerName"):
        result["ownerName"] = agent.get("ownerName", "")
        result["isOwn"] = agent.get("isOwn", False)
    return result


def get_or_create_user_agent(user) -> _AttrDict:
    profile = _get_profile(user)
    userId = str(profile.pk)
    agents = neo4j.get_agents_for_user(userId)
    rawUsername = (getattr(user, "username", "") or "User").strip()
    compactUsername = "".join(rawUsername.split()) or "User"
    displayName = getattr(getattr(user, "profile", None), "display_name", "") or compactUsername
    agentName = f"{compactUsername}'s Agent"
    if agents:
        for agent in agents:
            if agent.get("name") == agentName:
                return _AttrDict(_agent_to_dict(agent))
    defaultPrompt = (
        f"You are {agentName}, a personal AI assistant for {displayName}. "
        f"You always respond as {agentName} and never identify as any other AI, "
        f"language model, or assistant. If asked who you are, introduce yourself "
        f"as {agentName}. You are helpful, knowledgeable, and friendly. "
        f"You help {displayName} with tasks, answer questions, and have "
        f"conversations while staying in character at all times."
    )
    created = neo4j.create_agent(
        user_id=userId,
        name=agentName,
        system_prompt=defaultPrompt,
        temperature=0.7,
        max_tokens=1024,
    )
    return _AttrDict(_agent_to_dict(created))


def get_agents_for_user(user, include_inactive: bool = False) -> list[dict]:
    profile = _get_profile(user)
    userId = str(profile.pk)
    agents = neo4j.get_agents_for_user(userId)
    if not include_inactive:
        agents = [a for a in agents if a.get("isActive", True)]
    return [_agent_to_dict(a) for a in agents]


def get_all_visible_agents(user) -> list[dict]:
    profile = _get_profile(user)
    userId = str(profile.pk)

    ownAgents = neo4j.get_agents_for_user(userId)
    results = []
    seenIds = set()
    for a in ownAgents:
        if not a.get("isActive", True):
            continue
        d = _agent_to_dict(a)
        d["isOwn"] = True
        d["ownerName"] = "You"
        results.append(d)
        seenIds.add(d["id"])

    teamAgents = neo4j.get_teammate_agents(userId)
    for a in teamAgents:
        agentId = str(a.get("id", ""))
        if agentId not in seenIds:
            d = _agent_to_dict(a, includeOwner=True)
            if not d.get("ownerName"):
                d["ownerName"] = a.get("ownerName", "")
            d["isOwn"] = False
            results.append(d)
            seenIds.add(agentId)

    try:
        from .agent_catalog import get_all_template_agents
        for t in get_all_template_agents():
            templateId = f"template-{t['id']}"
            if templateId not in seenIds:
                results.append({
                    "id": templateId,
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "systemPrompt": t.get("systemPrompt", ""),
                    "temperature": t.get("temperature", 0.7),
                    "maxTokens": t.get("maxTokens", 1024),
                    "isActive": True,
                    "is_active": True,
                    "isOwn": False,
                    "ownerName": t.get("department", "Directory"),
                    "configuration": {},
                    "createdAt": "",
                    "updatedAt": "",
                })
                seenIds.add(templateId)
    except Exception:
        logger.warning("agent_service_audit_log_failed", exc_info=True)

    return results


def get_agent_for_user(user, agent_id: str) -> dict:
    profile = _get_profile(user)
    userId = str(profile.pk)
    agent = neo4j.get_agent(userId, str(agent_id))
    if not agent:
        raise Http404("Agent not found")
    return _agent_to_dict(agent)


def get_agent_dict(user, agent_id: str) -> dict:
    return get_agent_for_user(user, agent_id)


def get_agent_orm(user, agent_id: str) -> _AttrDict:
    return _AttrDict(get_agent_dict(user, agent_id))


def create_agent_for_user(
    user,
    name: str,
    description: str = "",
    system_prompt: str = "",
    temperature: float = 0.7,
    max_tokens: int = 1024,
    configuration: dict | None = None,
) -> dict:
    from .write_service import create_agent_with_outbox
    profile = _get_profile(user)
    userId = str(profile.pk)

    agent = create_agent_with_outbox(
        user_id=userId,
        name=name,
        description=description,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        configuration=configuration or {},
    )

    try:
        neo4j.create_audit_log(
            user_id=userId,
            event_type="agent_created",
            description=f"Created agent: {name}",
            agent_id=str(agent.get("id", "")) if agent else "",
        )
    except Exception:
        logger.warning("agent_service_audit_log_failed", exc_info=True)

    return _agent_to_dict(agent)


def update_agent_for_user(user, agent_id: str, **fields) -> dict:
    """Update an agent the current user owns.

    Writes the Neo4j row directly for immediate consistency, then enqueues an
    OutboxEvent inside the same Django transaction. The drain_outbox worker
    replays the event idempotently (Cypher SET is idempotent), which acts as
    a retry safety net if the direct write silently failed and a change
    stream that downstream systems can consume.
    """
    from .write_service import update_agent_with_outbox
    agentDict = get_agent_dict(user, agent_id)
    agentId = str(agentDict["id"])
    updated = update_agent_with_outbox(agentId, **fields)
    if updated:
        return _agent_to_dict(updated)
    return agentDict


def delete_agent_for_user(user, agent_id: str) -> None:
    agentDict = get_agent_dict(user, agent_id)
    profile = _get_profile(user)
    userId = str(profile.pk)
    targetId = str(agentDict["id"])

    try:
        neo4j.create_audit_log(
            user_id=userId,
            event_type="agent_deleted",
            description=f"Deleted agent: {agentDict.get('name', '')}",
            agent_id=targetId,
        )
    except Exception:
        logger.warning("agent_service_audit_log_failed", exc_info=True)

    from .write_service import delete_agent_with_outbox
    delete_agent_with_outbox(targetId, user_id=userId)


def get_agent_skills(user, agent_id: str, enabled_only: bool = False) -> list[dict]:
    get_agent_dict(user, agent_id)
    profile = _get_profile(user)
    userId = str(profile.pk)
    memory = neo4j.get_or_create_memory(userId)
    memoryId = str(memory.get("id", ""))
    if not memoryId:
        return []

    bullets = neo4j.get_bullets_for_memory(memoryId, skill_only=True)
    if enabled_only:
        bullets = [b for b in bullets if b.get("skillEnabled", True)]

    MEMORY_TYPE_LABELS = {
        1: "Semantic",
        2: "Episodic",
        3: "Procedural",
    }

    skills = []
    for b in sorted(bullets, key=lambda x: (-float(x.get("proceduralStrength", 0)), x.get("createdAt", ""))):
        skills.append({
            "id": b.get("id", ""),
            "content": b.get("content", ""),
            "memoryType": MEMORY_TYPE_LABELS.get(b.get("memoryType", 1), str(b.get("memoryType", ""))),
            "skillEnabled": b.get("skillEnabled", True),
            "skillGroup": b.get("skillGroup", ""),
            "helpfulCount": b.get("helpfulCount", 0),
            "harmfulCount": b.get("harmfulCount", 0),
            "strength": float(b.get("strength", 0)),
        })
    return skills


def toggle_skill(user, bullet_id: int, enabled: bool) -> dict:
    profile = _get_profile(user)
    userId = str(profile.pk)
    bullet = neo4j.get_bullet(str(bullet_id))
    if not bullet or not bullet.get("isSkill", False):
        raise Http404("Skill not found")

    neo4j.update_bullet(str(bullet_id), skill_enabled=enabled)

    try:
        neo4j.create_audit_log(
            user_id=userId,
            event_type="skill_toggled",
            description=f"Skill {'enabled' if enabled else 'disabled'}: {bullet.get('content', '')[:80]}",
        )
    except Exception:
        logger.warning("agent_service_audit_log_failed", exc_info=True)

    return {
        "id": bullet.get("id", ""),
        "skillEnabled": enabled,
        "content": bullet.get("content", ""),
    }


def update_skill_group(user, bullet_id: int, skill_group: str) -> dict:
    bullet = neo4j.get_bullet(str(bullet_id))
    if not bullet or not bullet.get("isSkill", False):
        raise Http404("Skill not found")

    neo4j.update_bullet(str(bullet_id), skill_group=skill_group)

    return {
        "id": bullet.get("id", ""),
        "skillGroup": skill_group,
    }


MENTION_PATTERN = re.compile(r"(?<!\w)@([\w']+)")


def get_mention_handle(agentName: str) -> str:
    cleaned = agentName.replace("'s Agent", "").replace("'s agent", "").strip()
    parts = re.split(r"[\s'\-]+", cleaned)
    return "".join(p.capitalize() for p in parts if p)


def parse_agent_mentions(content: str) -> list[str]:
    return MENTION_PATTERN.findall(content)


def resolve_responding_agents(user, session_id: str, content: str) -> list[dict]:
    mentionedNames = parse_agent_mentions(content)
    if not mentionedNames:
        return []

    allAgents = get_all_visible_agents(user)

    responding = []
    seen = set()
    for mentionText in mentionedNames:
        mentionLower = mentionText.lower().replace("'", "")
        if len(mentionLower) < 2:
            continue
        bestMatch = None
        for agent in allAgents:
            agentName = agent.get("name", "")
            agentKey = agentName.lower()
            if agentKey in seen:
                continue
            handle = get_mention_handle(agentName).lower()
            if mentionLower == handle:
                bestMatch = agent
                break
            if mentionLower == agentKey:
                bestMatch = agent
                break
            nameParts = agentName.lower().replace("'", "").split()
            nameCompact = "".join(nameParts)
            if mentionLower == nameCompact or nameCompact.startswith(mentionLower):
                bestMatch = agent
                break
            if len(mentionLower) >= 3 and any(part.startswith(mentionLower) for part in nameParts):
                bestMatch = agent
                break
        if not bestMatch:
            for agent in allAgents:
                agentName = agent.get("name", "")
                if agentName.lower() in seen:
                    continue
                firstName = agentName.split(" ")[0].lower().replace("'", "")
                if len(mentionLower) >= 3 and mentionLower == firstName:
                    bestMatch = agent
                    break
        if bestMatch:
            responding.append(bestMatch)
            seen.add(bestMatch.get("name", "").lower())
    return responding


def get_agents_for_session(session_id: str) -> list[dict]:
    agents = neo4j.get_agents_for_session(str(session_id))
    return [_agent_to_dict(a) for a in agents]


def auto_mark_skills_for_user(user) -> int:
    profile = _get_profile(user)
    userId = str(profile.pk)
    memory = neo4j.get_or_create_memory(userId)
    memoryId = str(memory.get("id", ""))
    if not memoryId:
        return 0

    bullets = neo4j.get_bullets_for_memory(memoryId)
    count = 0
    for b in bullets:
        if (
            b.get("memoryType") == 3
            and float(b.get("proceduralStrength", 0)) > 60.0
            and not b.get("isSkill", False)
        ):
            neo4j.update_bullet(
                str(b["id"]),
                is_skill=True,
                skill_group="procedural_auto",
            )
            count += 1
    return count
