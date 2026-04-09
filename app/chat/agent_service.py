import re

from django.http import Http404

from app.chat.models.agent import Agent
from app.services import neo4j_memory as neo4j


def _get_profile(user):
    from app.chat.service import get_or_create_profile_for_user
    return get_or_create_profile_for_user(user)


def _agent_to_dict(a: Agent) -> dict:
    return {
        "id": str(a.pk),
        "name": a.name,
        "description": a.description,
        "systemPrompt": a.system_prompt,
        "temperature": float(a.temperature),
        "maxTokens": a.max_tokens,
        "isActive": a.is_active,
        "configuration": a.configuration or {},
        "createdAt": a.created_at.isoformat() if a.created_at else "",
        "updatedAt": a.updated_at.isoformat() if a.updated_at else "",
    }


def get_or_create_user_agent(user) -> Agent:
    profile = _get_profile(user)
    agent = Agent.objects.filter(user=profile).first()
    if agent is None:
        agent = Agent.objects.create(
            user=profile,
            name="My Assistant",
            temperature=0.7,
            max_tokens=1024,
        )
    return agent


def get_agents_for_user(user, include_inactive: bool = False) -> list[dict]:
    profile = _get_profile(user)
    qs = Agent.objects.filter(user=profile)
    if not include_inactive:
        qs = qs.filter(is_active=True)
    return [_agent_to_dict(a) for a in qs.order_by("-created_at")]


def get_agent_for_user(user, agent_id: str) -> dict:
    profile = _get_profile(user)
    try:
        a = Agent.objects.get(pk=int(agent_id), user=profile)
    except (ValueError, Agent.DoesNotExist):
        raise Http404("Agent not found")
    return _agent_to_dict(a)


def get_agent_orm(user, agent_id: str) -> Agent:
    profile = _get_profile(user)
    try:
        return Agent.objects.get(pk=int(agent_id), user=profile)
    except (ValueError, Agent.DoesNotExist):
        raise Http404("Agent not found")


def create_agent_for_user(
    user,
    name: str,
    description: str = "",
    system_prompt: str = "",
    temperature: float = 0.7,
    max_tokens: int = 1024,
    configuration: dict | None = None,
) -> dict:
    profile = _get_profile(user)
    agent = Agent.objects.create(
        user=profile,
        name=name,
        description=description,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        configuration=configuration or {},
    )

    try:
        neo4j.sync_agent_to_neo4j(str(profile.pk), agent)
    except Exception:
        pass

    try:
        neo4j.create_audit_log(
            user_id=str(profile.pk),
            event_type="agent_created",
            description=f"Created agent: {name}",
            agent_id=str(agent.pk),
        )
    except Exception:
        pass

    return _agent_to_dict(agent)


def update_agent_for_user(user, agent_id: str, **fields) -> dict:
    agent = get_agent_orm(user, agent_id)

    fieldMap = {
        "name": "name",
        "description": "description",
        "system_prompt": "system_prompt",
        "temperature": "temperature",
        "max_tokens": "max_tokens",
        "is_active": "is_active",
    }
    updateFields = []
    for key, attrName in fieldMap.items():
        if key in fields:
            setattr(agent, attrName, fields[key])
            updateFields.append(attrName)
    if "configuration" in fields:
        agent.configuration = fields["configuration"]
        updateFields.append("configuration")

    if updateFields:
        agent.save(update_fields=updateFields + ["updated_at"])

    try:
        neo4j.update_agent(str(agent.pk), **fields)
    except Exception:
        pass

    return _agent_to_dict(agent)


def delete_agent_for_user(user, agent_id: str) -> None:
    agent = get_agent_orm(user, agent_id)
    agentName = agent.name

    try:
        profile = _get_profile(user)
        neo4j.create_audit_log(
            user_id=str(profile.pk),
            event_type="agent_deleted",
            description=f"Deleted agent: {agentName}",
            agent_id=str(agent.pk),
        )
        neo4j.delete_agent(str(agent.pk))
    except Exception:
        pass

    agent.delete()


def get_agent_skills(user, agent_id: str, enabled_only: bool = False) -> list[dict]:
    get_agent_orm(user, agent_id)

    from app.chat.models.memory_bullet import MemoryBullet

    profile = _get_profile(user)
    qs = MemoryBullet.objects.filter(memory__user=profile, is_skill=True)
    if enabled_only:
        qs = qs.filter(skill_enabled=True)

    skills = []
    for bullet in qs.order_by("-procedural_strength", "-created_at"):
        skills.append({
            "id": bullet.pk,
            "content": bullet.content,
            "memoryType": bullet.get_memory_type_display() if hasattr(bullet, "get_memory_type_display") else str(bullet.memory_type),
            "skillEnabled": bullet.skill_enabled,
            "skillGroup": bullet.skill_group or "",
            "helpfulCount": bullet.helpful_count,
            "harmfulCount": bullet.harmful_count,
            "strength": float(bullet.strength),
        })
    return skills


def toggle_skill(user, bullet_id: int, enabled: bool) -> dict:
    from app.chat.models.memory_bullet import MemoryBullet

    profile = _get_profile(user)
    try:
        bullet = MemoryBullet.objects.get(pk=bullet_id, memory__user=profile, is_skill=True)
    except MemoryBullet.DoesNotExist:
        raise Http404("Skill not found")

    MemoryBullet.objects.filter(pk=bullet_id).update(skill_enabled=enabled)
    bullet.refresh_from_db()

    try:
        neo4j.create_audit_log(
            user_id=str(profile.pk),
            event_type="skill_toggled",
            description=f"Skill {'enabled' if enabled else 'disabled'}: {bullet.content[:80]}",
        )
    except Exception:
        pass

    return {"id": bullet.pk, "skillEnabled": bullet.skill_enabled, "content": bullet.content}


def update_skill_group(user, bullet_id: int, skill_group: str) -> dict:
    from app.chat.models.memory_bullet import MemoryBullet

    profile = _get_profile(user)
    try:
        bullet = MemoryBullet.objects.get(pk=bullet_id, memory__user=profile, is_skill=True)
    except MemoryBullet.DoesNotExist:
        raise Http404("Skill not found")

    MemoryBullet.objects.filter(pk=bullet_id).update(skill_group=skill_group)
    bullet.refresh_from_db()
    return {"id": bullet.pk, "skillGroup": bullet.skill_group}


MENTION_PATTERN = re.compile(r"@(\w+)")


def parse_agent_mentions(content: str) -> list[str]:
    return MENTION_PATTERN.findall(content)


def resolve_responding_agents(user, session_id: str, content: str) -> list[dict]:
    mentionedNames = parse_agent_mentions(content)
    if not mentionedNames:
        return []

    allAgents = get_agents_for_user(user)
    agentsByName = {a.get("name", "").lower(): a for a in allAgents}

    responding = []
    for name in mentionedNames:
        agent = agentsByName.get(name.lower())
        if agent:
            responding.append(agent)
    return responding


def get_agents_for_session(session_id: str) -> list[dict]:
    from app.chat.models.session_participant import SessionParticipant
    participants = SessionParticipant.objects.filter(
        session_id=session_id
    ).select_related("agent")
    return [_agent_to_dict(p.agent) for p in participants if p.agent]


def auto_mark_skills_for_user(user) -> int:
    from app.chat.models.memory_bullet import MemoryBullet

    profile = _get_profile(user)
    return MemoryBullet.objects.filter(
        memory__user=profile,
        memory_type=3,
        procedural_strength__gt=60.0,
        is_skill=False,
    ).update(is_skill=True, skill_group="procedural_auto")
