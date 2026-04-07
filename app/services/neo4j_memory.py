import json
import os
import threading
import time
from typing import Any, Dict, Optional

_DRIVER = None
_DRIVER_LOCK = threading.Lock()


def _get_driver():
    global _DRIVER
    if _DRIVER is not None:
        return _DRIVER

    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")

    if not uri or not user or not password:
        return None

    try:
        from neo4j import GraphDatabase

        with _DRIVER_LOCK:
            if _DRIVER is None:
                _DRIVER = GraphDatabase.driver(uri, auth=(user, password))
        return _DRIVER
    except Exception:
        return None


def _get_database() -> Optional[str]:
    return os.getenv("NEO4J_DATABASE") or None


def _safe_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except Exception:
        return default
    return parsed if parsed >= 0 else default


def _safe_env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except Exception:
        return default
    return parsed if parsed >= 0.0 else default


def _reset_driver() -> None:
    global _DRIVER
    with _DRIVER_LOCK:
        if _DRIVER is not None:
            try:
                _DRIVER.close()
            except Exception:
                pass
            _DRIVER = None


class Neo4jMemoryStore:

    def __init__(self, learner_id: str):
        if not learner_id:
            raise ValueError("learner_id is required for Neo4jMemoryStore")
        self.learner_id = learner_id
        self._database = _get_database()
        self._retry_max = _safe_env_int("ACE_NEO4J_RETRY_MAX", 2)
        self._retry_backoff_sec = _safe_env_float("ACE_NEO4J_RETRY_BACKOFF_SEC", 1.0)

    def _run_with_retry(self, operation_name: str, fn) -> Dict[str, Any]:
        max_attempts = self._retry_max + 1
        last_error = ""
        for attempt in range(max_attempts):
            try:
                value = fn()
                return {
                    "ok": True,
                    "value": value,
                    "attempts": attempt + 1,
                    "retries": attempt,
                    "error": "",
                }
            except Exception as exc:
                last_error = str(exc)
                is_last = attempt >= max_attempts - 1
                from neo4j.exceptions import SessionExpired
                if isinstance(exc, SessionExpired):
                    _reset_driver()
                if is_last:
                    return {
                        "ok": False,
                        "value": None,
                        "attempts": attempt + 1,
                        "retries": attempt,
                        "error": last_error,
                    }
                sleep_sec = self._retry_backoff_sec * (2 ** attempt)
                if sleep_sec > 0:
                    time.sleep(sleep_sec)
        return {
            "ok": False,
            "value": None,
            "attempts": max_attempts,
            "retries": max_attempts - 1,
            "error": last_error,
        }

    def load(self) -> Optional[Dict[str, Any]]:
        def _op() -> Optional[Dict[str, Any]]:
            driver = _get_driver()
            if driver is None:
                return None
            with driver.session(database=self._database) as session:
                record = session.run(
                    """
                    MATCH (u:User {id: $userId})
                    MERGE (u)-[:HAS_ACE_MEMORY]->(m:AceMemoryState)
                    ON CREATE SET
                        m.id = randomUUID(),
                        m.memory_json = $emptyPayload,
                        m.access_clock = 0,
                        m.created_at = datetime(),
                        m.updated_at = datetime()
                    RETURN m.memory_json AS memory_json,
                           m.access_clock AS access_clock
                    """,
                    {
                        "userId": self.learner_id,
                        "emptyPayload": json.dumps(
                            {"bullets": [], "access_clock": 0}, ensure_ascii=False
                        ),
                    },
                ).single()
                if not record:
                    return None
                raw = record.get("memory_json")
                if not raw:
                    return None
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    return None
                access_clock = record.get("access_clock")
                if access_clock is not None:
                    try:
                        access_clock = int(access_clock)
                    except (TypeError, ValueError):
                        pass
                if access_clock is not None and "access_clock" not in data:
                    data["access_clock"] = access_clock
                return data
        result = self._run_with_retry("load", _op)
        if not result.get("ok"):
            return None
        return result.get("value")

    def save(self, data: Dict[str, Any]) -> Dict[str, Any]:
        payload = json.dumps(data, ensure_ascii=False)
        access_clock = int(data.get("access_clock", 0))

        def _op() -> None:
            driver = _get_driver()
            if driver is None:
                return None
            with driver.session(database=self._database) as session:
                session.run(
                    """
                    MERGE (u:User {id: $userId})
                    ON CREATE SET u.created_at = datetime()
                    MERGE (u)-[:HAS_ACE_MEMORY]->(m:AceMemoryState)
                    ON CREATE SET
                        m.id = randomUUID(),
                        m.created_at = datetime()
                    SET m.memory_json = $memory_json,
                        m.access_clock = $access_clock,
                        m.updated_at = datetime()
                    """,
                    {
                        "userId": self.learner_id,
                        "memory_json": payload,
                        "access_clock": access_clock,
                    },
                )
            return None

        result = self._run_with_retry("save", _op)
        return {
            "ok": bool(result.get("ok", False)),
            "attempts": int(result.get("attempts", 1)),
            "retries": int(result.get("retries", 0)),
            "error": str(result.get("error", "")),
        }


def sync_memory_to_neo4j(learner_id: str, memory_obj) -> Dict[str, Any]:
    from app.chat.models.memory_bullet import MemoryBullet

    driver = _get_driver()
    if driver is None:
        return {"ok": False, "error": "neo4j_not_configured"}

    bullets_qs = MemoryBullet.objects.filter(memory=memory_obj)
    bullets_data = []
    for b in bullets_qs:
        bullets_data.append({
            "id": str(b.pk),
            "content": b.content,
            "helpful_count": b.helpful_count,
            "harmful_count": b.harmful_count,
            "tags": b.tags or [],
            "memory_type": b.get_memory_type_display() if hasattr(b, "get_memory_type_display") else str(b.memory_type),
            "topic": b.topic or "",
            "strength": b.strength,
            "semantic_strength": float(b.semantic_strength or 0),
            "episodic_strength": float(b.episodic_strength or 0),
            "procedural_strength": float(b.procedural_strength or 0),
            "learner_id": b.learner_id or "",
            "context_scope_id": b.context_scope_id or "",
            "content_hash": b.content_hash or "",
            "created_at": b.created_at.isoformat() if b.created_at else "",
        })

    data = {
        "bullets": bullets_data,
        "access_clock": memory_obj.access_clock,
        "version": "django_sync_1.0",
    }

    store = Neo4jMemoryStore(learner_id=learner_id)
    return store.save(data)


def _run_query(cypher: str, params: dict | None = None) -> list[dict]:
    driver = _get_driver()
    if driver is None:
        return []
    database = _get_database()
    try:
        with driver.session(database=database) as session:
            result = session.run(cypher, params or {})
            return [dict(record) for record in result]
    except Exception:
        return []


def _run_single(cypher: str, params: dict | None = None) -> dict | None:
    rows = _run_query(cypher, params)
    if rows:
        return rows[0]
    return None


def _node_to_dict(node) -> dict:
    if node is None:
        return {}
    if hasattr(node, "items"):
        data = dict(node.items())
    elif isinstance(node, dict):
        data = dict(node)
    else:
        data = {}
    for key, value in data.items():
        if hasattr(value, "isoformat"):
            data[key] = value.isoformat()
    return data


def create_agent(
    user_id: str,
    name: str,
    description: str = "",
    system_prompt: str = "",
    temperature: float = 0.7,
    max_tokens: int = 1024,
    configuration: dict | None = None,
) -> dict:
    record = _run_single(
        """
        MERGE (u:User {id: $userId})
        ON CREATE SET u.createdAt = datetime()
        CREATE (a:Agent {
            id: randomUUID(),
            name: $name,
            description: $description,
            systemPrompt: $systemPrompt,
            temperature: $temperature,
            maxTokens: $maxTokens,
            isActive: true,
            configuration: $configuration,
            createdAt: datetime(),
            updatedAt: datetime()
        })
        CREATE (u)-[:OWNS]->(a)
        RETURN a
        """,
        {
            "userId": str(user_id),
            "name": name,
            "description": description,
            "systemPrompt": system_prompt,
            "temperature": temperature,
            "maxTokens": max_tokens,
            "configuration": json.dumps(configuration or {}),
        },
    )
    if record and "a" in record:
        return _node_to_dict(record["a"])
    return {}


def get_agents_for_user(user_id: str) -> list[dict]:
    rows = _run_query(
        """
        MATCH (u:User {id: $userId})-[:OWNS]->(a:Agent)
        RETURN a
        ORDER BY a.createdAt DESC
        """,
        {"userId": str(user_id)},
    )
    return [_node_to_dict(row["a"]) for row in rows if "a" in row]


def get_agent(user_id: str, agent_id: str) -> dict | None:
    record = _run_single(
        """
        MATCH (u:User {id: $userId})-[:OWNS]->(a:Agent {id: $agentId})
        RETURN a
        """,
        {"userId": str(user_id), "agentId": str(agent_id)},
    )
    if record and "a" in record:
        return _node_to_dict(record["a"])
    return None


def update_agent(agent_id: str, **fields) -> dict | None:
    set_clauses = ["a.updatedAt = datetime()"]
    params: dict = {"agentId": str(agent_id)}
    field_map = {
        "name": "name", "description": "description",
        "system_prompt": "systemPrompt", "temperature": "temperature",
        "max_tokens": "maxTokens", "is_active": "isActive",
    }
    for py_name, neo_name in field_map.items():
        if py_name in fields:
            set_clauses.append(f"a.{neo_name} = ${py_name}")
            params[py_name] = fields[py_name]
    if "configuration" in fields:
        set_clauses.append("a.configuration = $configuration")
        params["configuration"] = json.dumps(fields["configuration"])

    record = _run_single(
        f"""
        MATCH (a:Agent {{id: $agentId}})
        SET {", ".join(set_clauses)}
        RETURN a
        """,
        params,
    )
    if record and "a" in record:
        return _node_to_dict(record["a"])
    return None


def delete_agent(agent_id: str) -> None:
    _run_query(
        """
        MATCH (a:Agent {id: $agentId})
        DETACH DELETE a
        """,
        {"agentId": str(agent_id)},
    )


def create_session(
    user_id: str,
    title: str,
    agent_ids: list[str] | None = None,
) -> dict:
    record = _run_single(
        """
        MERGE (u:User {id: $userId})
        ON CREATE SET u.createdAt = datetime()
        CREATE (s:Session {
            id: randomUUID(),
            title: $title,
            createdAt: datetime(),
            updatedAt: datetime()
        })
        CREATE (u)-[:CREATED]->(s)
        RETURN s
        """,
        {"userId": str(user_id), "title": title},
    )
    session_data = _node_to_dict(record.get("a") if record else None) if not record else _node_to_dict(record.get("s", {}))

    if session_data and agent_ids:
        session_id = session_data.get("id", "")
        for aid in agent_ids:
            add_agent_to_session(session_id, aid)

    return session_data


def get_sessions_for_user(user_id: str) -> list[dict]:
    rows = _run_query(
        """
        MATCH (u:User {id: $userId})-[:CREATED]->(s:Session)
        RETURN s
        ORDER BY s.updatedAt DESC
        """,
        {"userId": str(user_id)},
    )
    return [_node_to_dict(row["s"]) for row in rows if "s" in row]


def get_session(user_id: str, session_id: str) -> dict | None:
    record = _run_single(
        """
        MATCH (u:User {id: $userId})-[:CREATED]->(s:Session {id: $sessionId})
        RETURN s
        """,
        {"userId": str(user_id), "sessionId": str(session_id)},
    )
    if record and "s" in record:
        return _node_to_dict(record["s"])
    return None


def add_agent_to_session(session_id: str, agent_id: str) -> dict:
    record = _run_single(
        """
        MATCH (a:Agent {id: $agentId})
        MATCH (s:Session {id: $sessionId})
        MERGE (a)-[r:PARTICIPATED_IN]->(s)
        ON CREATE SET r.joinedAt = datetime()
        RETURN a, s
        """,
        {"agentId": str(agent_id), "sessionId": str(session_id)},
    )
    return _node_to_dict(record.get("a", {})) if record else {}


def delete_session(session_id: str) -> None:
    _run_query(
        """
        MATCH (s:Session {id: $sessionId})
        OPTIONAL MATCH (s)-[:CONTAINS]->(m:Message)
        DETACH DELETE m, s
        """,
        {"sessionId": str(session_id)},
    )


def create_message(
    session_id: str,
    content: str,
    created_by: str,
    role: str = "user",
    sender_agent_id: str | None = None,
    is_ai: bool = False,
) -> dict:
    params = {
        "sessionId": str(session_id),
        "content": content,
        "createdBy": str(created_by),
        "role": role,
        "isAi": is_ai,
    }

    if sender_agent_id:
        record = _run_single(
            """
            MATCH (s:Session {id: $sessionId})
            MATCH (a:Agent {id: $agentId})
            CREATE (m:Message {
                id: randomUUID(),
                content: $content,
                role: $role,
                createdBy: $createdBy,
                isAi: $isAi,
                edited: false,
                createdAt: datetime()
            })
            CREATE (s)-[:CONTAINS]->(m)
            CREATE (a)-[:POSTED]->(m)
            SET s.updatedAt = datetime()
            RETURN m
            """,
            {**params, "agentId": str(sender_agent_id)},
        )
    else:
        record = _run_single(
            """
            MATCH (s:Session {id: $sessionId})
            MERGE (u:User {id: $createdBy})
            ON CREATE SET u.createdAt = datetime()
            CREATE (m:Message {
                id: randomUUID(),
                content: $content,
                role: $role,
                createdBy: $createdBy,
                isAi: $isAi,
                edited: false,
                createdAt: datetime()
            })
            CREATE (s)-[:CONTAINS]->(m)
            CREATE (u)-[:POSTED]->(m)
            SET s.updatedAt = datetime()
            RETURN m
            """,
            params,
        )

    if record and "m" in record:
        return _node_to_dict(record["m"])
    return {}


def get_messages_for_session(
    session_id: str,
    skip: int = 0,
    limit: int = 50,
) -> list[dict]:
    rows = _run_query(
        """
        MATCH (s:Session {id: $sessionId})-[:CONTAINS]->(m:Message)
        OPTIONAL MATCH (a:Agent)-[:POSTED]->(m)
        RETURN m, a.name AS agentName, a.id AS agentId
        ORDER BY m.createdAt ASC
        SKIP $skip
        LIMIT $limit
        """,
        {"sessionId": str(session_id), "skip": skip, "limit": limit},
    )
    results = []
    for row in rows:
        msg = _node_to_dict(row.get("m", {}))
        msg["agentName"] = row.get("agentName")
        msg["agentId"] = row.get("agentId")
        results.append(msg)
    return results


def edit_message(message_id: str, new_content: str) -> dict | None:
    record = _run_single(
        """
        MATCH (m:Message {id: $messageId})
        SET m.content = $content, m.edited = true
        RETURN m
        """,
        {"messageId": str(message_id), "content": new_content},
    )
    if record and "m" in record:
        return _node_to_dict(record["m"])
    return None


def delete_message(message_id: str) -> None:
    _run_query(
        "MATCH (m:Message {id: $messageId}) DETACH DELETE m",
        {"messageId": str(message_id)},
    )


def create_notification(
    user_id: str,
    title: str,
    message: str,
    notification_type: int,
    related_url: str = "",
) -> dict:
    record = _run_single(
        """
        MERGE (u:User {id: $userId})
        ON CREATE SET u.createdAt = datetime()
        CREATE (n:Notification {
            id: randomUUID(),
            title: $title,
            message: $message,
            notificationType: $notificationType,
            isRead: false,
            relatedUrl: $relatedUrl,
            createdAt: datetime()
        })
        CREATE (u)-[:HAS_NOTIFICATION]->(n)
        RETURN n
        """,
        {
            "userId": str(user_id),
            "title": title,
            "message": message,
            "notificationType": notification_type,
            "relatedUrl": related_url,
        },
    )
    if record and "n" in record:
        return _node_to_dict(record["n"])
    return {}


def get_notifications(
    user_id: str,
    unread_only: bool = False,
    limit: int = 10,
) -> list[dict]:
    where_clause = "AND n.isRead = false" if unread_only else ""
    rows = _run_query(
        f"""
        MATCH (u:User {{id: $userId}})-[:HAS_NOTIFICATION]->(n:Notification)
        WHERE true {where_clause}
        RETURN n
        ORDER BY n.createdAt DESC
        LIMIT $limit
        """,
        {"userId": str(user_id), "limit": limit},
    )
    return [_node_to_dict(row["n"]) for row in rows if "n" in row]


def get_unread_notification_count(user_id: str) -> int:
    record = _run_single(
        """
        MATCH (u:User {id: $userId})-[:HAS_NOTIFICATION]->(n:Notification {isRead: false})
        RETURN count(n) AS cnt
        """,
        {"userId": str(user_id)},
    )
    if record:
        return int(record.get("cnt", 0))
    return 0


def mark_notification_read(notification_id: str) -> None:
    _run_query(
        """
        MATCH (n:Notification {id: $notificationId})
        SET n.isRead = true
        """,
        {"notificationId": str(notification_id)},
    )


def mark_all_notifications_read(user_id: str) -> int:
    record = _run_single(
        """
        MATCH (u:User {id: $userId})-[:HAS_NOTIFICATION]->(n:Notification {isRead: false})
        SET n.isRead = true
        RETURN count(n) AS cnt
        """,
        {"userId": str(user_id)},
    )
    if record:
        return int(record.get("cnt", 0))
    return 0


def create_audit_log(
    user_id: str,
    event_type: str,
    description: str = "",
    agent_id: str | None = None,
    metadata: dict | None = None,
) -> dict:
    if agent_id:
        record = _run_single(
            """
            MERGE (u:User {id: $userId})
            ON CREATE SET u.createdAt = datetime()
            MATCH (a:Agent {id: $agentId})
            CREATE (al:AuditLog {
                id: randomUUID(),
                eventType: $eventType,
                description: $description,
                metadata: $metadata,
                createdAt: datetime()
            })
            CREATE (u)-[:HAS_LOG]->(al)
            CREATE (a)-[:TRIGGERED]->(al)
            RETURN al
            """,
            {
                "userId": str(user_id),
                "agentId": str(agent_id),
                "eventType": event_type,
                "description": description,
                "metadata": json.dumps(metadata or {}),
            },
        )
    else:
        record = _run_single(
            """
            MERGE (u:User {id: $userId})
            ON CREATE SET u.createdAt = datetime()
            CREATE (al:AuditLog {
                id: randomUUID(),
                eventType: $eventType,
                description: $description,
                metadata: $metadata,
                createdAt: datetime()
            })
            CREATE (u)-[:HAS_LOG]->(al)
            RETURN al
            """,
            {
                "userId": str(user_id),
                "eventType": event_type,
                "description": description,
                "metadata": json.dumps(metadata or {}),
            },
        )
    if record and "al" in record:
        return _node_to_dict(record["al"])
    return {}


def get_audit_logs(
    user_id: str,
    event_type: str = "",
    limit: int = 100,
) -> list[dict]:
    where_clause = "AND al.eventType = $eventType" if event_type else ""
    params: dict = {"userId": str(user_id), "limit": limit}
    if event_type:
        params["eventType"] = event_type
    rows = _run_query(
        f"""
        MATCH (u:User {{id: $userId}})-[:HAS_LOG]->(al:AuditLog)
        WHERE true {where_clause}
        OPTIONAL MATCH (a:Agent)-[:TRIGGERED]->(al)
        RETURN al, a.name AS agentName, a.id AS agentId
        ORDER BY al.createdAt DESC
        LIMIT $limit
        """,
        params,
    )
    results = []
    for row in rows:
        log = _node_to_dict(row.get("al", {}))
        log["agentName"] = row.get("agentName")
        log["agentId"] = row.get("agentId")
        results.append(log)
    return results


def get_activity_feed(user_id: str, limit: int = 20) -> list[dict]:
    return get_audit_logs(user_id, limit=limit)


def sync_agent_to_neo4j(user_id: str, agent) -> dict:
    try:
        return create_agent(
            user_id=str(user_id),
            name=agent.name,
            description=agent.description or "",
            system_prompt=agent.system_prompt or "",
            temperature=float(agent.temperature),
            max_tokens=int(agent.max_tokens),
            configuration=agent.configuration or {},
        )
    except Exception:
        return {}


def sync_agent_skills_to_neo4j(agent_id: str, bullets) -> dict:
    driver = _get_driver()
    if driver is None:
        return {"ok": False, "error": "neo4j_not_configured"}
    database = _get_database()
    count = 0
    try:
        with driver.session(database=database) as session:
            for b in bullets:
                session.run(
                    """
                    MATCH (a:Agent {id: $agentId})
                    MERGE (s:MemoryBullet {id: $bulletId})
                    ON CREATE SET
                        s.content = $content,
                        s.isSkill = true,
                        s.skillEnabled = $enabled,
                        s.createdAt = datetime()
                    ON MATCH SET
                        s.content = $content,
                        s.isSkill = true,
                        s.skillEnabled = $enabled
                    MERGE (a)-[:HAS_SKILL]->(s)
                    """,
                    {
                        "agentId": str(agent_id),
                        "bulletId": str(b.pk if hasattr(b, "pk") else b.get("id", "")),
                        "content": b.content if hasattr(b, "content") else b.get("content", ""),
                        "enabled": bool(b.skill_enabled if hasattr(b, "skill_enabled") else b.get("skillEnabled", True)),
                    },
                )
                count += 1
    except Exception:
        return {"ok": False, "error": "sync_failed", "count": count}
    return {"ok": True, "count": count}


def sync_session_to_neo4j(user_id: str, session_obj) -> dict:
    try:
        return create_session(
            user_id=str(user_id),
            title=session_obj.title or "",
        )
    except Exception:
        return {}


def init_neo4j_constraints() -> bool:
    driver = _get_driver()
    if driver is None:
        return False
    database = _get_database()
    constraints = [
        "CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (u:User) REQUIRE u.id IS UNIQUE",
        "CREATE CONSTRAINT agent_id_unique IF NOT EXISTS FOR (a:Agent) REQUIRE a.id IS UNIQUE",
        "CREATE CONSTRAINT session_id_unique IF NOT EXISTS FOR (s:Session) REQUIRE s.id IS UNIQUE",
        "CREATE CONSTRAINT message_id_unique IF NOT EXISTS FOR (m:Message) REQUIRE m.id IS UNIQUE",
        "CREATE CONSTRAINT notification_id_unique IF NOT EXISTS FOR (n:Notification) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT audit_id_unique IF NOT EXISTS FOR (al:AuditLog) REQUIRE al.id IS UNIQUE",
    ]
    try:
        with driver.session(database=database) as session:
            for cypher in constraints:
                try:
                    session.run(cypher)
                except Exception:
                    pass
        return True
    except Exception:
        return False
