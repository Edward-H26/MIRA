import json
import os
import re
import threading
import time
from typing import Any, Dict, Optional

_DRIVER = None
_DRIVER_LOCK = threading.Lock()

_NEO_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _safe_identifier(name: str) -> str:
    if not _NEO_IDENTIFIER_RE.match(name):
        raise ValueError(f"invalid Neo4j identifier: {name!r}")
    return name


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
                _DRIVER = GraphDatabase.driver(
                    uri,
                    auth=(user, password),
                    max_connection_pool_size=_safe_env_int(
                        "NEO4J_MAX_CONNECTION_POOL_SIZE", 32
                    ),
                    connection_timeout=_safe_env_float(
                        "NEO4J_CONNECTION_TIMEOUT", 30.0
                    ),
                    max_transaction_retry_time=_safe_env_float(
                        "NEO4J_MAX_TX_RETRY", 15.0
                    ),
                    keep_alive=True,
                )
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
            set_clauses.append(f"a.{_safe_identifier(neo_name)} = ${_safe_identifier(py_name)}")
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
    sender_agent_name: str = "",
    is_ai: bool = False,
) -> dict:
    params = {
        "sessionId": str(session_id),
        "content": content,
        "createdBy": str(created_by),
        "role": role,
        "isAi": is_ai,
        "senderAgentName": sender_agent_name,
    }

    if sender_agent_id:
        record = _run_single(
            """
            MATCH (s:Session {id: $sessionId})
            CREATE (m:Message {
                id: randomUUID(),
                content: $content,
                role: $role,
                createdBy: $createdBy,
                isAi: $isAi,
                senderAgentName: $senderAgentName,
                edited: false,
                createdAt: datetime()
            })
            CREATE (s)-[:CONTAINS]->(m)
            SET s.updatedAt = datetime()
            WITH m
            OPTIONAL MATCH (a:Agent {id: $agentId})
            FOREACH (_ IN CASE WHEN a IS NOT NULL THEN [1] ELSE [] END |
                CREATE (a)-[:POSTED]->(m)
            )
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
                senderAgentName: $senderAgentName,
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


def get_total_message_count_for_user(user_id: str) -> int:
    record = _run_single(
        """
        MATCH (u:User {id: $userId})-[:CREATED]->(s:Session)-[:CONTAINS]->(m:Message)
        RETURN count(m) AS cnt
        """,
        {"userId": str(user_id)},
    )
    return record["cnt"] if record and "cnt" in record else 0


def get_message_counts_by_session(user_id: str) -> dict:
    rows = _run_query(
        """
        MATCH (u:User {id: $userId})-[:CREATED]->(s:Session)
        OPTIONAL MATCH (s)-[:CONTAINS]->(m:Message)
        RETURN s.id AS sessionId, s.createdAt AS createdAt, count(m) AS msgCount
        """,
        {"userId": str(user_id)},
    )
    return {str(row["sessionId"]): {"count": row["msgCount"], "createdAt": row["createdAt"]} for row in rows}


def get_messages_for_session(
    session_id: str,
    skip: int = 0,
    limit: int = 200,
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
        msg["agentName"] = row.get("agentName") or msg.get("senderAgentName", "")
        msg["agentId"] = row.get("agentId")
        try:
            msg["role"] = int(msg["role"])
        except (ValueError, TypeError, KeyError):
            pass
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


def mark_notifications_read_by_related_url(user_id: str, related_url: str) -> int:
    if not related_url:
        return 0
    record = _run_single(
        """
        MATCH (u:User {id: $userId})-[:HAS_NOTIFICATION]->(n:Notification {isRead: false})
        WHERE n.relatedUrl = $relatedUrl
        SET n.isRead = true
        RETURN count(n) AS cnt
        """,
        {"userId": str(user_id), "relatedUrl": str(related_url)},
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


def create_or_update_django_user(
    user_id: str,
    username: str,
    email: str = "",
    password_hash: str = "",
    display_name: str = "",
    is_active: bool = True,
    is_staff: bool = False,
    is_superuser: bool = False,
    first_name: str = "",
    last_name: str = "",
    uuid: str = "",
) -> dict:
    record = _run_single(
        """
        MERGE (u:User {id: $userId})
        ON CREATE SET
            u.username = $username, u.email = $email,
            u.passwordHash = $passwordHash, u.displayName = $displayName,
            u.isActive = $isActive, u.isStaff = $isStaff,
            u.isSuperuser = $isSuperuser, u.firstName = $firstName,
            u.lastName = $lastName, u.uuid = $uuid,
            u.createdAt = datetime(), u.lastLogin = null
        ON MATCH SET
            u.username = $username, u.email = $email,
            u.displayName = $displayName, u.isActive = $isActive,
            u.isStaff = $isStaff, u.isSuperuser = $isSuperuser,
            u.firstName = $firstName, u.lastName = $lastName
        RETURN u
        """,
        {
            "userId": str(user_id), "username": username, "email": email,
            "passwordHash": password_hash, "displayName": display_name,
            "isActive": is_active, "isStaff": is_staff,
            "isSuperuser": is_superuser, "firstName": first_name,
            "lastName": last_name, "uuid": uuid,
        },
    )
    if record and "u" in record:
        return _node_to_dict(record["u"])
    return {}


def update_user_password(user_id: str, password_hash: str) -> None:
    _run_query(
        "MATCH (u:User {id: $userId}) SET u.passwordHash = $hash",
        {"userId": str(user_id), "hash": password_hash},
    )


def update_user_last_login(user_id: str) -> None:
    _run_query(
        "MATCH (u:User {id: $userId}) SET u.lastLogin = datetime()",
        {"userId": str(user_id)},
    )


def get_user_by_username(username: str) -> dict | None:
    record = _run_single(
        "MATCH (u:User {username: $username}) RETURN u",
        {"username": username},
    )
    if record and "u" in record:
        return _node_to_dict(record["u"])
    return None


def get_user_by_id(user_id: str) -> dict | None:
    record = _run_single(
        "MATCH (u:User {id: $userId}) RETURN u",
        {"userId": str(user_id)},
    )
    if record and "u" in record:
        return _node_to_dict(record["u"])
    return None


def get_user_by_email(email: str) -> dict | None:
    record = _run_single(
        "MATCH (u:User {email: $email}) RETURN u",
        {"email": email},
    )
    if record and "u" in record:
        return _node_to_dict(record["u"])
    return None


def save_django_session(session_key: str, session_data: str, expire_date: str) -> None:
    _run_query(
        """
        MERGE (s:DjangoSession {sessionKey: $key})
        SET s.sessionData = $data, s.expireDate = datetime($expire)
        """,
        {"key": session_key, "data": session_data, "expire": expire_date},
    )


def load_django_session(session_key: str) -> dict | None:
    record = _run_single(
        """
        MATCH (s:DjangoSession {sessionKey: $key})
        WHERE s.expireDate > datetime()
        RETURN s.sessionData AS data, s.expireDate AS expire
        """,
        {"key": session_key},
    )
    if record:
        return {"data": record.get("data"), "expire": record.get("expire")}
    return None


def delete_django_session(session_key: str) -> None:
    _run_query(
        "MATCH (s:DjangoSession {sessionKey: $key}) DELETE s",
        {"key": session_key},
    )


def django_session_exists(session_key: str) -> bool:
    record = _run_single(
        "MATCH (s:DjangoSession {sessionKey: $key}) RETURN count(s) AS cnt",
        {"key": session_key},
    )
    return bool(record and int(record.get("cnt", 0)) > 0)


def cleanup_expired_sessions() -> int:
    record = _run_single(
        """
        MATCH (s:DjangoSession) WHERE s.expireDate <= datetime()
        WITH s, count(s) AS cnt
        DELETE s
        RETURN cnt
        """,
        {},
    )
    return int(record.get("cnt", 0)) if record else 0


def update_session(session_id: str, **fields) -> dict | None:
    set_clauses = ["s.updatedAt = datetime()"]
    params: dict = {"sessionId": str(session_id)}
    field_map = {
        "title": "title",
        "description": "description",
        "access_key": "accessKey",
    }
    for py_name, neo_name in field_map.items():
        if py_name in fields:
            set_clauses.append(f"s.{neo_name} = ${py_name}")
            params[py_name] = fields[py_name]
    record = _run_single(
        f"""
        MATCH (s:Session {{id: $sessionId}})
        SET {", ".join(set_clauses)}
        RETURN s
        """,
        params,
    )
    if record and "s" in record:
        return _node_to_dict(record["s"])
    return None


def acquire_session_generation_lock(session_id: str) -> bool:
    from django.utils import timezone
    from datetime import timedelta
    import os
    timeout = int(os.getenv("CHAT_GENERATION_LOCK_TIMEOUT_SECONDS", "60"))
    now = timezone.now()
    cutoff = (now - timedelta(seconds=timeout)).isoformat()
    nowStr = now.isoformat()
    record = _run_single(
        """
        MATCH (s:Session {id: $sessionId})
        WHERE s.generationInProgress IS NULL
              OR s.generationInProgress = false
              OR (s.generationStartedAt IS NOT NULL AND s.generationStartedAt <= datetime($cutoff))
        SET s.generationInProgress = true, s.generationStartedAt = datetime($now)
        RETURN true AS acquired
        """,
        {"sessionId": str(session_id), "cutoff": cutoff, "now": nowStr},
    )
    return bool(record and record.get("acquired"))


def release_session_generation_lock(session_id: str) -> None:
    _run_query(
        """
        MATCH (s:Session {id: $sessionId})
        SET s.generationInProgress = false, s.generationStartedAt = null
        """,
        {"sessionId": str(session_id)},
    )


def ensure_generation_lock_fresh(session_id: str) -> bool:
    import os
    from django.utils import timezone
    from datetime import timedelta
    timeout = int(os.getenv("CHAT_GENERATION_LOCK_TIMEOUT_SECONDS", "60"))
    cutoff = (timezone.now() - timedelta(seconds=timeout)).isoformat()
    _run_query(
        """
        MATCH (s:Session {id: $sessionId})
        WHERE s.generationInProgress = true
              AND s.generationStartedAt IS NOT NULL
              AND s.generationStartedAt <= datetime($cutoff)
        SET s.generationInProgress = false, s.generationStartedAt = null
        """,
        {"sessionId": str(session_id), "cutoff": cutoff},
    )
    record = _run_single(
        "MATCH (s:Session {id: $sessionId}) RETURN s.generationInProgress AS inProgress",
        {"sessionId": str(session_id)},
    )
    return bool(record and record.get("inProgress"))


def session_has_messages(session_id: str) -> bool:
    record = _run_single(
        """
        MATCH (s:Session {id: $sessionId})-[:CONTAINS]->(m:Message)
        RETURN count(m) AS cnt LIMIT 1
        """,
        {"sessionId": str(session_id)},
    )
    return bool(record and int(record.get("cnt", 0)) > 0)


def update_session_generation_lock(session_id: str, in_progress: bool, started_at: str | None = None) -> None:
    params: dict = {"sessionId": str(session_id), "inProgress": in_progress}
    if in_progress and started_at:
        _run_query(
            """
            MATCH (s:Session {id: $sessionId})
            SET s.generationInProgress = $inProgress,
                s.generationStartedAt = datetime($startedAt)
            """,
            {**params, "startedAt": started_at},
        )
    else:
        _run_query(
            """
            MATCH (s:Session {id: $sessionId})
            SET s.generationInProgress = $inProgress,
                s.generationStartedAt = null
            """,
            params,
        )


def create_document(
    user_id: str,
    filename: str,
    raw_text: str = "",
    description: str = "",
    parsed_fields: dict | None = None,
    file_size: str = "",
    ttl_days: int = 7,
    agent_id: str | None = None,
) -> dict:
    params = {
        "userId": str(user_id),
        "filename": filename,
        "rawText": raw_text,
        "description": description,
        "parsedFields": json.dumps(parsed_fields or {}),
        "fileSize": file_size,
        "ttlDays": ttl_days,
    }
    if agent_id:
        record = _run_single(
            """
            MERGE (u:User {id: $userId})
            ON CREATE SET u.createdAt = datetime()
            MATCH (a:Agent {id: $agentId})
            CREATE (d:Document {
                id: randomUUID(), filename: $filename, rawText: $rawText,
                description: $description, parsedFields: $parsedFields,
                fileSize: $fileSize, ttlDays: $ttlDays, createdAt: datetime()
            })
            CREATE (u)-[:HAS_DOCUMENT]->(d)
            CREATE (a)-[:HAS_DOCUMENT]->(d)
            RETURN d
            """,
            {**params, "agentId": str(agent_id)},
        )
    else:
        record = _run_single(
            """
            MERGE (u:User {id: $userId})
            ON CREATE SET u.createdAt = datetime()
            CREATE (d:Document {
                id: randomUUID(), filename: $filename, rawText: $rawText,
                description: $description, parsedFields: $parsedFields,
                fileSize: $fileSize, ttlDays: $ttlDays, createdAt: datetime()
            })
            CREATE (u)-[:HAS_DOCUMENT]->(d)
            RETURN d
            """,
            params,
        )
    if record and "d" in record:
        return _node_to_dict(record["d"])
    return {}


def get_documents_for_user(user_id: str, agent_id: str | None = None) -> list[dict]:
    if agent_id:
        rows = _run_query(
            """
            MATCH (u:User {id: $userId})-[:HAS_DOCUMENT]->(d:Document)
            MATCH (a:Agent {id: $agentId})-[:HAS_DOCUMENT]->(d)
            RETURN d ORDER BY d.createdAt DESC
            """,
            {"userId": str(user_id), "agentId": str(agent_id)},
        )
    else:
        rows = _run_query(
            """
            MATCH (u:User {id: $userId})-[:HAS_DOCUMENT]->(d:Document)
            RETURN d ORDER BY d.createdAt DESC
            """,
            {"userId": str(user_id)},
        )
    return [_node_to_dict(row["d"]) for row in rows if "d" in row]


def get_document(document_id: str) -> dict | None:
    record = _run_single(
        "MATCH (d:Document {id: $docId}) RETURN d",
        {"docId": str(document_id)},
    )
    if record and "d" in record:
        return _node_to_dict(record["d"])
    return None


def update_document_parsed_fields(document_id: str, parsed_fields: dict) -> None:
    _run_query(
        """
        MATCH (d:Document {id: $docId})
        SET d.parsedFields = $pf
        """,
        {"docId": str(document_id), "pf": json.dumps(parsed_fields)},
    )


def delete_document(document_id: str) -> None:
    _run_query(
        "MATCH (d:Document {id: $docId}) DETACH DELETE d",
        {"docId": str(document_id)},
    )


def update_document(document_id: str, **fields) -> dict | None:
    set_clauses = []
    params: dict = {"docId": str(document_id)}
    field_map = {
        "description": "description",
        "filename": "filename",
        "raw_text": "rawText",
        "file_size": "fileSize",
    }
    for py_name, neo_name in field_map.items():
        if py_name in fields:
            set_clauses.append(f"d.{neo_name} = ${py_name}")
            params[py_name] = fields[py_name]
    if not set_clauses:
        return get_document(document_id)
    record = _run_single(
        f"""
        MATCH (d:Document {{id: $docId}})
        SET {", ".join(set_clauses)}
        RETURN d
        """,
        params,
    )
    if record and "d" in record:
        return _node_to_dict(record["d"])
    return None


def delete_vote(user_id: str, bullet_id: str) -> None:
    _run_query(
        """
        MATCH (u:User {id: $userId})-[v:VOTED]->(mb:MemoryBullet {id: $bulletId})
        DELETE v
        """,
        {"userId": str(user_id), "bulletId": str(bullet_id)},
    )


def create_skill(
    user_id: str,
    name: str,
    slug: str,
    description: str = "",
    content: str = "",
    category: str = "",
    is_enabled: bool = True,
    source: str = "template",
    source_bullet_ids: list | None = None,
) -> dict:
    record = _run_single(
        """
        MERGE (u:User {id: $userId})
        ON CREATE SET u.createdAt = datetime()
        CREATE (sk:Skill {
            id: randomUUID(), name: $name, slug: $slug,
            description: $description, content: $content,
            category: $category, isEnabled: $isEnabled,
            source: $source, sourceBulletIds: $sourceBulletIds,
            createdAt: datetime(), updatedAt: datetime()
        })
        CREATE (u)-[:HAS_SKILL]->(sk)
        RETURN sk
        """,
        {
            "userId": str(user_id),
            "name": name,
            "slug": slug,
            "description": description,
            "content": content,
            "category": category,
            "isEnabled": is_enabled,
            "source": source,
            "sourceBulletIds": json.dumps(source_bullet_ids or []),
        },
    )
    if record and "sk" in record:
        return _node_to_dict(record["sk"])
    return {}


def get_skills_for_user(user_id: str, enabled_only: bool = False) -> list[dict]:
    where = "AND sk.isEnabled = true" if enabled_only else ""
    rows = _run_query(
        f"""
        MATCH (u:User {{id: $userId}})-[:HAS_SKILL]->(sk:Skill)
        WHERE true {where}
        RETURN sk ORDER BY sk.updatedAt DESC
        """,
        {"userId": str(user_id)},
    )
    return [_node_to_dict(row["sk"]) for row in rows if "sk" in row]


def get_skill(skill_id: str) -> dict | None:
    record = _run_single(
        "MATCH (sk:Skill {id: $skId}) RETURN sk",
        {"skId": str(skill_id)},
    )
    if record and "sk" in record:
        return _node_to_dict(record["sk"])
    return None


def get_skill_by_slug(user_id: str, slug: str) -> dict | None:
    record = _run_single(
        """
        MATCH (u:User {id: $userId})-[:HAS_SKILL]->(sk:Skill {slug: $slug})
        RETURN sk
        """,
        {"userId": str(user_id), "slug": slug},
    )
    if record and "sk" in record:
        return _node_to_dict(record["sk"])
    return None


def update_skill(skill_id: str, **fields) -> dict | None:
    set_clauses = ["sk.updatedAt = datetime()"]
    params: dict = {"skId": str(skill_id)}
    field_map = {
        "name": "name", "slug": "slug", "description": "description",
        "content": "content", "category": "category",
        "is_enabled": "isEnabled", "source": "source",
    }
    for py_name, neo_name in field_map.items():
        if py_name in fields:
            set_clauses.append(f"sk.{neo_name} = ${py_name}")
            params[py_name] = fields[py_name]
    if "source_bullet_ids" in fields:
        set_clauses.append("sk.sourceBulletIds = $sourceBulletIds")
        params["sourceBulletIds"] = json.dumps(fields["source_bullet_ids"])
    record = _run_single(
        f"""
        MATCH (sk:Skill {{id: $skId}})
        SET {", ".join(set_clauses)}
        RETURN sk
        """,
        params,
    )
    if record and "sk" in record:
        return _node_to_dict(record["sk"])
    return None


def delete_skill(skill_id: str) -> None:
    _run_query(
        "MATCH (sk:Skill {id: $skId}) DETACH DELETE sk",
        {"skId": str(skill_id)},
    )


def upsert_vote(user_id: str, bullet_id: str, value: int) -> dict:
    record = _run_single(
        """
        MATCH (u:User {id: $userId})
        MATCH (mb:MemoryBullet {id: $bulletId})
        MERGE (u)-[v:VOTED]->(mb)
        ON CREATE SET v.value = $value, v.createdAt = datetime(), v.updatedAt = datetime()
        ON MATCH SET v.value = $value, v.updatedAt = datetime()
        RETURN v.value AS value, mb.id AS bulletId
        """,
        {"userId": str(user_id), "bulletId": str(bullet_id), "value": value},
    )
    if record:
        return {"bulletId": record.get("bulletId"), "value": record.get("value")}
    return {}


def get_user_vote(user_id: str, bullet_id: str) -> int | None:
    record = _run_single(
        """
        MATCH (u:User {id: $userId})-[v:VOTED]->(mb:MemoryBullet {id: $bulletId})
        RETURN v.value AS value
        """,
        {"userId": str(user_id), "bulletId": str(bullet_id)},
    )
    if record:
        return record.get("value")
    return None


def get_user_votes_batch(user_id: str, bullet_ids: list[str]) -> dict[str, int]:
    if not bullet_ids:
        return {}
    rows = _run_query(
        """
        MATCH (u:User {id: $userId})-[v:VOTED]->(mb:MemoryBullet)
        WHERE mb.id IN $bulletIds
        RETURN mb.id AS bulletId, v.value AS value
        """,
        {"userId": str(user_id), "bulletIds": [str(b) for b in bullet_ids]},
    )
    return {str(row["bulletId"]): row["value"] for row in rows}


def create_request_log(
    user_id: str,
    session_id: str | None = None,
    request_type: str = "chat",
    model_name: str = "",
    pipeline: str = "gemini_direct",
    status: str = "success",
    latency_ms: int = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    estimated_cost_usd: float = 0.0,
    error_type: str = "",
    metadata: dict | None = None,
) -> dict:
    params = {
        "userId": str(user_id),
        "requestType": request_type,
        "modelName": model_name,
        "pipeline": pipeline,
        "status": status,
        "latencyMs": latency_ms,
        "promptTokens": prompt_tokens,
        "completionTokens": completion_tokens,
        "totalTokens": total_tokens,
        "estimatedCostUsd": estimated_cost_usd,
        "errorType": error_type,
        "metadata": json.dumps(metadata or {}),
    }
    if session_id:
        record = _run_single(
            """
            MERGE (u:User {id: $userId})
            ON CREATE SET u.createdAt = datetime()
            CREATE (rl:RequestLog {
                id: randomUUID(), requestType: $requestType,
                modelName: $modelName, pipeline: $pipeline, status: $status,
                latencyMs: $latencyMs, promptTokens: $promptTokens,
                completionTokens: $completionTokens, totalTokens: $totalTokens,
                estimatedCostUsd: $estimatedCostUsd, errorType: $errorType,
                metadata: $metadata, createdAt: datetime()
            })
            CREATE (u)-[:HAS_REQUEST_LOG]->(rl)
            WITH rl
            OPTIONAL MATCH (s:Session {id: $sessionId})
            FOREACH (_ IN CASE WHEN s IS NOT NULL THEN [1] ELSE [] END |
                CREATE (s)-[:HAS_REQUEST_LOG]->(rl)
            )
            RETURN rl
            """,
            {**params, "sessionId": str(session_id)},
        )
    else:
        record = _run_single(
            """
            MERGE (u:User {id: $userId})
            ON CREATE SET u.createdAt = datetime()
            CREATE (rl:RequestLog {
                id: randomUUID(), requestType: $requestType,
                modelName: $modelName, pipeline: $pipeline, status: $status,
                latencyMs: $latencyMs, promptTokens: $promptTokens,
                completionTokens: $completionTokens, totalTokens: $totalTokens,
                estimatedCostUsd: $estimatedCostUsd, errorType: $errorType,
                metadata: $metadata, createdAt: datetime()
            })
            CREATE (u)-[:HAS_REQUEST_LOG]->(rl)
            RETURN rl
            """,
            params,
        )
    if record and "rl" in record:
        return _node_to_dict(record["rl"])
    return {}


def get_request_logs_for_user(user_id: str, limit: int = 100) -> list[dict]:
    rows = _run_query(
        """
        MATCH (u:User {id: $userId})-[:HAS_REQUEST_LOG]->(rl:RequestLog)
        RETURN rl ORDER BY rl.createdAt DESC LIMIT $limit
        """,
        {"userId": str(user_id), "limit": limit},
    )
    return [_node_to_dict(row["rl"]) for row in rows if "rl" in row]


def aggregate_request_stats(user_id: str, days: int = 30) -> dict:
    record = _run_single(
        """
        MATCH (u:User {id: $userId})-[:HAS_REQUEST_LOG]->(rl:RequestLog)
        WHERE rl.createdAt >= datetime() - duration({days: $days})
        RETURN count(rl) AS totalRequests,
               avg(rl.latencyMs) AS avgLatency,
               sum(rl.totalTokens) AS totalTokens,
               sum(rl.estimatedCostUsd) AS totalCost,
               sum(CASE WHEN rl.status = 'error' THEN 1 ELSE 0 END) AS errorCount
        """,
        {"userId": str(user_id), "days": days},
    )
    if record:
        return {
            "totalRequests": int(record.get("totalRequests") or 0),
            "avgLatency": float(record.get("avgLatency") or 0),
            "totalTokens": int(record.get("totalTokens") or 0),
            "totalCost": float(record.get("totalCost") or 0),
            "errorCount": int(record.get("errorCount") or 0),
        }
    return {"totalRequests": 0, "avgLatency": 0, "totalTokens": 0, "totalCost": 0, "errorCount": 0}


def get_request_logs_by_date(user_id: str, days: int = 30) -> list[dict]:
    rows = _run_query(
        """
        MATCH (u:User {id: $userId})-[:HAS_REQUEST_LOG]->(rl:RequestLog)
        WHERE rl.createdAt >= datetime() - duration({days: $days})
        RETURN rl ORDER BY rl.createdAt DESC
        """,
        {"userId": str(user_id), "days": days},
    )
    return [_node_to_dict(row["rl"]) for row in rows if "rl" in row]


def create_plan(
    name: str, code: str, description: str,
    interval: int, price_cents: int,
    currency: str = "USD", is_active: bool = True,
) -> dict:
    record = _run_single(
        """
        CREATE (p:Plan {
            id: randomUUID(), name: $name, code: $code,
            description: $description, interval: $interval,
            priceCents: $priceCents, currency: $currency,
            isActive: $isActive, createdAt: datetime()
        })
        RETURN p
        """,
        {
            "name": name, "code": code, "description": description,
            "interval": interval, "priceCents": price_cents,
            "currency": currency, "isActive": is_active,
        },
    )
    if record and "p" in record:
        return _node_to_dict(record["p"])
    return {}


def get_plans(active_only: bool = True) -> list[dict]:
    where = "WHERE p.isActive = true" if active_only else ""
    rows = _run_query(
        f"MATCH (p:Plan) {where} RETURN p ORDER BY p.name",
        {},
    )
    return [_node_to_dict(row["p"]) for row in rows if "p" in row]


def get_plan_by_code(code: str, interval: int) -> dict | None:
    record = _run_single(
        "MATCH (p:Plan {code: $code, interval: $interval}) RETURN p",
        {"code": code, "interval": interval},
    )
    if record and "p" in record:
        return _node_to_dict(record["p"])
    return None


def create_subscription(
    user_id: str, plan_id: str,
    status: int = 0, auto_renew: bool = False,
    period_start: str = "", period_end: str = "",
) -> dict:
    record = _run_single(
        """
        MERGE (u:User {id: $userId})
        ON CREATE SET u.createdAt = datetime()
        MATCH (p:Plan {id: $planId})
        CREATE (sub:Subscription {
            id: randomUUID(), status: $status,
            autoRenew: $autoRenew,
            currentPeriodStart: $periodStart,
            currentPeriodEnd: $periodEnd,
            createdAt: datetime(), updatedAt: datetime()
        })
        CREATE (u)-[:HAS_SUBSCRIPTION]->(sub)
        CREATE (sub)-[:FOR_PLAN]->(p)
        RETURN sub
        """,
        {
            "userId": str(user_id), "planId": str(plan_id),
            "status": status, "autoRenew": auto_renew,
            "periodStart": period_start, "periodEnd": period_end,
        },
    )
    if record and "sub" in record:
        return _node_to_dict(record["sub"])
    return {}


def get_subscription_for_user(user_id: str) -> dict | None:
    record = _run_single(
        """
        MATCH (u:User {id: $userId})-[:HAS_SUBSCRIPTION]->(sub:Subscription)
        OPTIONAL MATCH (sub)-[:FOR_PLAN]->(p:Plan)
        RETURN sub, p.name AS planName, p.code AS planCode
        ORDER BY sub.updatedAt DESC LIMIT 1
        """,
        {"userId": str(user_id)},
    )
    if record and "sub" in record:
        data = _node_to_dict(record["sub"])
        data["planName"] = record.get("planName")
        data["planCode"] = record.get("planCode")
        return data
    return None


def update_subscription_status(subscription_id: str, status: int) -> None:
    _run_query(
        """
        MATCH (sub:Subscription {id: $subId})
        SET sub.status = $status, sub.updatedAt = datetime()
        """,
        {"subId": str(subscription_id), "status": status},
    )


def create_payment(
    user_id: str,
    subscription_id: str | None = None,
    plan_id: str | None = None,
    amount_cents: int = 0,
    currency: str = "USD",
    status: int = 1,
) -> dict:
    params = {
        "userId": str(user_id),
        "amountCents": amount_cents,
        "currency": currency,
        "status": status,
    }
    cypher = """
        MERGE (u:User {id: $userId})
        ON CREATE SET u.createdAt = datetime()
        CREATE (pay:Payment {
            id: randomUUID(), amountCents: $amountCents,
            currency: $currency, status: $status,
            paidAt: null, createdAt: datetime()
        })
        CREATE (u)-[:MADE_PAYMENT]->(pay)
    """
    if subscription_id:
        cypher += "\nWITH pay\nMATCH (sub:Subscription {id: $subId})\nCREATE (pay)-[:FOR_SUBSCRIPTION]->(sub)"
        params["subId"] = str(subscription_id)
    if plan_id:
        cypher += "\nWITH pay\nMATCH (p:Plan {id: $planId})\nCREATE (pay)-[:FOR_PLAN]->(p)"
        params["planId"] = str(plan_id)
    cypher += "\nRETURN pay"
    record = _run_single(cypher, params)
    if record and "pay" in record:
        return _node_to_dict(record["pay"])
    return {}


def get_payments_for_user(user_id: str, limit: int = 20) -> list[dict]:
    rows = _run_query(
        """
        MATCH (u:User {id: $userId})-[:MADE_PAYMENT]->(pay:Payment)
        RETURN pay ORDER BY pay.createdAt DESC LIMIT $limit
        """,
        {"userId": str(user_id), "limit": limit},
    )
    return [_node_to_dict(row["pay"]) for row in rows if "pay" in row]


def add_member_to_session(session_id: str, user_id: str, role: str = "member") -> dict:
    record = _run_single(
        """
        MATCH (u:User {id: $userId})
        MATCH (s:Session {id: $sessionId})
        MERGE (u)-[r:MEMBER_OF]->(s)
        ON CREATE SET r.role = $role, r.joinedAt = datetime()
        ON MATCH SET r.role = $role
        RETURN u.id AS userId, s.id AS sessionId, r.role AS role
        """,
        {"userId": str(user_id), "sessionId": str(session_id), "role": role},
    )
    if record:
        return dict(record)
    return {}


def get_members_for_session(session_id: str) -> list[dict]:
    rows = _run_query(
        """
        MATCH (u:User)-[r:MEMBER_OF]->(s:Session {id: $sessionId})
        RETURN u.id AS userId, u.displayName AS displayName,
               u.username AS username, r.role AS role, r.joinedAt AS joinedAt
        ORDER BY r.joinedAt
        """,
        {"sessionId": str(session_id)},
    )
    return [dict(row) for row in rows]


def get_sessions_for_member(user_id: str) -> list[dict]:
    rows = _run_query(
        """
        MATCH (u:User {id: $userId})-[r:MEMBER_OF]->(s:Session)
        RETURN s, r.role AS role
        ORDER BY s.updatedAt DESC
        """,
        {"userId": str(user_id)},
    )
    results = []
    for row in rows:
        data = _node_to_dict(row.get("s", {}))
        data["memberRole"] = row.get("role")
        results.append(data)
    return results


def remove_member_from_session(session_id: str, user_id: str) -> None:
    _run_query(
        """
        MATCH (u:User {id: $userId})-[r:MEMBER_OF]->(s:Session {id: $sessionId})
        DELETE r
        """,
        {"userId": str(user_id), "sessionId": str(session_id)},
    )


def get_session_by_access_key(access_key: str) -> dict | None:
    record = _run_single(
        """
        MATCH (s:Session)
        WHERE s.accessKey = $accessKey
        RETURN s
        """,
        {"accessKey": access_key},
    )
    if record and "s" in record:
        return _node_to_dict(record["s"])
    return None


def get_session_by_id(session_id: str) -> dict | None:
    record = _run_single(
        "MATCH (s:Session {id: $sessionId}) RETURN s",
        {"sessionId": str(session_id)},
    )
    if record and "s" in record:
        return _node_to_dict(record["s"])
    return None


def count_session_members(session_id: str) -> int:
    record = _run_single(
        """
        MATCH (u:User)-[r:MEMBER_OF]->(s:Session {id: $sessionId})
        RETURN count(r) AS cnt
        """,
        {"sessionId": str(session_id)},
    )
    return int(record.get("cnt", 0)) if record else 0


def get_or_create_memory(user_id: str) -> dict:
    record = _run_single(
        """
        MERGE (u:User {id: $userId})
        ON CREATE SET u.createdAt = datetime()
        MERGE (u)-[:HAS_MEMORY]->(m:Memory)
        ON CREATE SET
            m.id = randomUUID(),
            m.accessClock = 0,
            m.plannerState = '{}',
            m.createdAt = datetime(),
            m.updatedAt = datetime()
        RETURN m
        """,
        {"userId": str(user_id)},
    )
    if record and "m" in record:
        data = _node_to_dict(record["m"])
        if isinstance(data.get("plannerState"), str):
            try:
                data["plannerState"] = json.loads(data["plannerState"])
            except (json.JSONDecodeError, TypeError):
                data["plannerState"] = {}
        return data
    return {"id": "", "accessClock": 0, "plannerState": {}}


def get_memory(memory_id: str) -> dict | None:
    record = _run_single(
        "MATCH (m:Memory {id: $mId}) RETURN m",
        {"mId": str(memory_id)},
    )
    if record and "m" in record:
        data = _node_to_dict(record["m"])
        if isinstance(data.get("plannerState"), str):
            try:
                data["plannerState"] = json.loads(data["plannerState"])
            except (json.JSONDecodeError, TypeError):
                data["plannerState"] = {}
        return data
    return None


def update_memory_fields(memory_id: str, **fields) -> None:
    set_clauses = ["m.updatedAt = datetime()"]
    params: dict = {"mId": str(memory_id)}
    if "access_clock" in fields:
        set_clauses.append("m.accessClock = $accessClock")
        params["accessClock"] = int(fields["access_clock"])
    if "planner_state" in fields:
        set_clauses.append("m.plannerState = $plannerState")
        params["plannerState"] = json.dumps(fields["planner_state"])
    _run_query(
        f"MATCH (m:Memory {{id: $mId}}) SET {', '.join(set_clauses)}",
        params,
    )


def create_bullet(
    memory_id: str,
    learner_id: str,
    content: str,
    tags: list | None = None,
    memory_type: int = 1,
    topic: str = "",
    strength: int = 100,
    ttl_days: int = 365,
    concept: str | None = None,
    bullet_key: str = "",
    context_scope_id: str = "",
    content_hash: str = "",
    semantic_strength: float = 0.0,
    episodic_strength: float = 0.0,
    procedural_strength: float = 0.0,
    semantic_access_index: int | None = None,
    episodic_access_index: int | None = None,
    procedural_access_index: int | None = None,
    is_skill: bool = False,
    skill_enabled: bool = True,
    skill_group: str = "",
    embedding_json: str = "",
) -> dict:
    record = _run_single(
        """
        MATCH (m:Memory {id: $memoryId})
        CREATE (mb:MemoryBullet {
            id: randomUUID(),
            content: $content, tags: $tags, memoryType: $memoryType,
            topic: $topic, strength: $strength, ttlDays: $ttlDays,
            concept: $concept, bulletKey: $bulletKey,
            contextScopeId: $contextScopeId, learnerId: $learnerId,
            contentHash: $contentHash,
            helpfulCount: 0, harmfulCount: 0,
            semanticStrength: $semanticStrength,
            episodicStrength: $episodicStrength,
            proceduralStrength: $proceduralStrength,
            semanticAccessIndex: $semanticAccessIndex,
            episodicAccessIndex: $episodicAccessIndex,
            proceduralAccessIndex: $proceduralAccessIndex,
            isSkill: $isSkill, skillEnabled: $skillEnabled,
            skillGroup: $skillGroup, embeddingJson: $embeddingJson,
            createdAt: datetime(), lastAccessed: datetime()
        })
        CREATE (m)-[:HAS_BULLET]->(mb)
        RETURN mb
        """,
        {
            "memoryId": str(memory_id), "learnerId": learner_id,
            "content": content, "tags": json.dumps(tags or []),
            "memoryType": memory_type, "topic": topic,
            "strength": strength, "ttlDays": ttl_days,
            "concept": concept, "bulletKey": bullet_key,
            "contextScopeId": context_scope_id,
            "contentHash": content_hash,
            "semanticStrength": semantic_strength,
            "episodicStrength": episodic_strength,
            "proceduralStrength": procedural_strength,
            "semanticAccessIndex": semantic_access_index,
            "episodicAccessIndex": episodic_access_index,
            "proceduralAccessIndex": procedural_access_index,
            "isSkill": is_skill, "skillEnabled": skill_enabled,
            "skillGroup": skill_group, "embeddingJson": embedding_json,
        },
    )
    if record and "mb" in record:
        data = _node_to_dict(record["mb"])
        if isinstance(data.get("tags"), str):
            try:
                data["tags"] = json.loads(data["tags"])
            except (json.JSONDecodeError, TypeError):
                data["tags"] = []
        return data
    return {}


def get_bullets_for_memory(
    memory_id: str,
    learner_id: str | None = None,
    context_scope_ids: list[str] | None = None,
    skill_only: bool = False,
) -> list[dict]:
    conditions = ["true"]
    params: dict = {"memoryId": str(memory_id)}
    if learner_id:
        conditions.append("mb.learnerId = $learnerId")
        params["learnerId"] = learner_id
    if context_scope_ids is not None:
        conditions.append("mb.contextScopeId IN $scopeIds")
        params["scopeIds"] = context_scope_ids
    if skill_only:
        conditions.append("mb.isSkill = true")
    rows = _run_query(
        f"""
        MATCH (m:Memory {{id: $memoryId}})-[:HAS_BULLET]->(mb:MemoryBullet)
        WHERE {" AND ".join(conditions)}
        RETURN mb ORDER BY mb.lastAccessed DESC
        """,
        params,
    )
    results = []
    for row in rows:
        if "mb" in row:
            data = _node_to_dict(row["mb"])
            if isinstance(data.get("tags"), str):
                try:
                    data["tags"] = json.loads(data["tags"])
                except (json.JSONDecodeError, TypeError):
                    data["tags"] = []
            results.append(data)
    return results


def get_bullet(bullet_id: str) -> dict | None:
    record = _run_single(
        "MATCH (mb:MemoryBullet {id: $bId}) RETURN mb",
        {"bId": str(bullet_id)},
    )
    if record and "mb" in record:
        data = _node_to_dict(record["mb"])
        if isinstance(data.get("tags"), str):
            try:
                data["tags"] = json.loads(data["tags"])
            except (json.JSONDecodeError, TypeError):
                data["tags"] = []
        return data
    return None


def get_bullet_by_content_hash(memory_id: str, content_hash: str) -> dict | None:
    record = _run_single(
        """
        MATCH (m:Memory {id: $memoryId})-[:HAS_BULLET]->(mb:MemoryBullet {contentHash: $hash})
        RETURN mb LIMIT 1
        """,
        {"memoryId": str(memory_id), "hash": content_hash},
    )
    if record and "mb" in record:
        data = _node_to_dict(record["mb"])
        if isinstance(data.get("tags"), str):
            try:
                data["tags"] = json.loads(data["tags"])
            except (json.JSONDecodeError, TypeError):
                data["tags"] = []
        return data
    return None


def update_bullet(bullet_id: str, **fields) -> None:
    set_clauses = []
    params: dict = {"bId": str(bullet_id)}
    field_map = {
        "content": "content", "strength": "strength",
        "helpful_count": "helpfulCount", "harmful_count": "harmfulCount",
        "content_hash": "contentHash",
        "semantic_strength": "semanticStrength",
        "episodic_strength": "episodicStrength",
        "procedural_strength": "proceduralStrength",
        "semantic_access_index": "semanticAccessIndex",
        "episodic_access_index": "episodicAccessIndex",
        "procedural_access_index": "proceduralAccessIndex",
        "is_skill": "isSkill", "skill_enabled": "skillEnabled",
        "skill_group": "skillGroup", "embedding_json": "embeddingJson",
    }
    for py_name, neo_name in field_map.items():
        if py_name in fields:
            set_clauses.append(f"mb.{_safe_identifier(neo_name)} = ${_safe_identifier(py_name)}")
            params[py_name] = fields[py_name]
    if "last_accessed" in fields:
        set_clauses.append("mb.lastAccessed = datetime($lastAccessed)")
        params["lastAccessed"] = fields["last_accessed"]
    if "semantic_last_access" in fields:
        val = fields["semantic_last_access"]
        if val:
            set_clauses.append("mb.semanticLastAccess = datetime($sla)")
            params["sla"] = val
    if "episodic_last_access" in fields:
        val = fields["episodic_last_access"]
        if val:
            set_clauses.append("mb.episodicLastAccess = datetime($ela)")
            params["ela"] = val
    if "procedural_last_access" in fields:
        val = fields["procedural_last_access"]
        if val:
            set_clauses.append("mb.proceduralLastAccess = datetime($pla)")
            params["pla"] = val
    if "tags" in fields:
        set_clauses.append("mb.tags = $tags")
        params["tags"] = json.dumps(fields["tags"])
    if not set_clauses:
        return
    _run_query(
        f"MATCH (mb:MemoryBullet {{id: $bId}}) SET {', '.join(set_clauses)}",
        params,
    )


def bulk_update_bullets(updates: list[dict]) -> int:
    driver = _get_driver()
    if driver is None:
        return 0
    database = _get_database()
    count = 0
    try:
        with driver.session(database=database) as session:
            for upd in updates:
                bullet_id = upd.pop("id", None)
                if not bullet_id:
                    continue
                update_bullet(str(bullet_id), **upd)
                count += 1
    except Exception:
        pass
    return count


def delete_bullet(bullet_id: str) -> None:
    _run_query(
        "MATCH (mb:MemoryBullet {id: $bId}) DETACH DELETE mb",
        {"bId": str(bullet_id)},
    )


def delete_bullets_by_ids(ids: list[str]) -> int:
    if not ids:
        return 0
    record = _run_single(
        """
        MATCH (mb:MemoryBullet) WHERE mb.id IN $ids
        WITH mb, count(mb) AS cnt
        DETACH DELETE mb
        RETURN cnt
        """,
        {"ids": [str(i) for i in ids]},
    )
    return int(record.get("cnt", 0)) if record else 0


def get_bullets_with_embeddings(memory_id: str, learner_id: str) -> list[dict]:
    rows = _run_query(
        """
        MATCH (m:Memory {id: $memoryId})-[:HAS_BULLET]->(mb:MemoryBullet)
        WHERE mb.learnerId = $learnerId AND mb.embeddingJson <> '' AND mb.embeddingJson IS NOT NULL
        RETURN mb.id AS id, mb.content AS content, mb.embeddingJson AS embeddingJson
        """,
        {"memoryId": str(memory_id), "learnerId": learner_id},
    )
    return [dict(row) for row in rows]


def get_messages_for_session_values(session_id: str, exclude_role: int | None = None, limit: int = 40) -> list[dict]:
    if exclude_role is not None:
        rows = _run_query(
            """
            MATCH (s:Session {id: $sessionId})-[:CONTAINS]->(m:Message)
            WHERE m.role <> $excludeRole AND m.role <> toString($excludeRole)
            RETURN m.role AS role, m.content AS content
            ORDER BY m.createdAt DESC LIMIT $limit
            """,
            {"sessionId": str(session_id), "excludeRole": exclude_role, "limit": limit},
        )
    else:
        rows = _run_query(
            """
            MATCH (s:Session {id: $sessionId})-[:CONTAINS]->(m:Message)
            RETURN m.role AS role, m.content AS content
            ORDER BY m.createdAt DESC LIMIT $limit
            """,
            {"sessionId": str(session_id), "limit": limit},
        )
    results = []
    for row in rows:
        d = dict(row)
        try:
            d["role"] = int(d["role"])
        except (ValueError, TypeError, KeyError):
            pass
        results.append(d)
    return results


def get_teammate_agents(user_id: str) -> list[dict]:
    rows = _run_query(
        """
        MATCH (u:User {id: $userId})-[:MEMBER_OF]->(s:Session)<-[:MEMBER_OF]-(other:User)
        WHERE other.id <> $userId
        MATCH (other)-[:OWNS]->(a:Agent {isActive: true})
        RETURN DISTINCT a, other.displayName AS ownerName
        """,
        {"userId": str(user_id)},
    )
    results = []
    for row in rows:
        if "a" in row:
            data = _node_to_dict(row["a"])
            data["ownerName"] = row.get("ownerName", "")
            data["isOwn"] = False
            results.append(data)
    return results


def get_agents_for_session(session_id: str) -> list[dict]:
    rows = _run_query(
        """
        MATCH (a:Agent)-[:PARTICIPATED_IN]->(s:Session {id: $sessionId})
        RETURN a ORDER BY a.name
        """,
        {"sessionId": str(session_id)},
    )
    return [_node_to_dict(row["a"]) for row in rows if "a" in row]


def init_neo4j_constraints() -> bool:
    driver = _get_driver()
    if driver is None:
        return False
    database = _get_database()
    statements = [
        "CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (u:User) REQUIRE u.id IS UNIQUE",
        "CREATE CONSTRAINT user_username_unique IF NOT EXISTS FOR (u:User) REQUIRE u.username IS UNIQUE",
        "CREATE CONSTRAINT agent_id_unique IF NOT EXISTS FOR (a:Agent) REQUIRE a.id IS UNIQUE",
        "CREATE CONSTRAINT session_id_unique IF NOT EXISTS FOR (s:Session) REQUIRE s.id IS UNIQUE",
        "CREATE CONSTRAINT message_id_unique IF NOT EXISTS FOR (m:Message) REQUIRE m.id IS UNIQUE",
        "CREATE CONSTRAINT notification_id_unique IF NOT EXISTS FOR (n:Notification) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT audit_id_unique IF NOT EXISTS FOR (al:AuditLog) REQUIRE al.id IS UNIQUE",
        "CREATE CONSTRAINT memory_id_unique IF NOT EXISTS FOR (mem:Memory) REQUIRE mem.id IS UNIQUE",
        "CREATE CONSTRAINT bullet_id_unique IF NOT EXISTS FOR (mb:MemoryBullet) REQUIRE mb.id IS UNIQUE",
        "CREATE CONSTRAINT document_id_unique IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
        "CREATE CONSTRAINT skill_id_unique IF NOT EXISTS FOR (sk:Skill) REQUIRE sk.id IS UNIQUE",
        "CREATE CONSTRAINT requestlog_id_unique IF NOT EXISTS FOR (rl:RequestLog) REQUIRE rl.id IS UNIQUE",
        "CREATE CONSTRAINT plan_id_unique IF NOT EXISTS FOR (p:Plan) REQUIRE p.id IS UNIQUE",
        "CREATE CONSTRAINT subscription_id_unique IF NOT EXISTS FOR (sub:Subscription) REQUIRE sub.id IS UNIQUE",
        "CREATE CONSTRAINT payment_id_unique IF NOT EXISTS FOR (pay:Payment) REQUIRE pay.id IS UNIQUE",
        "CREATE INDEX bullet_learner_idx IF NOT EXISTS FOR (mb:MemoryBullet) ON (mb.learnerId)",
        "CREATE INDEX bullet_content_hash_idx IF NOT EXISTS FOR (mb:MemoryBullet) ON (mb.contentHash)",
        "CREATE INDEX bullet_skill_idx IF NOT EXISTS FOR (mb:MemoryBullet) ON (mb.isSkill)",
        "CREATE INDEX session_access_key_idx IF NOT EXISTS FOR (s:Session) ON (s.accessKey)",
    ]
    try:
        with driver.session(database=database) as sess:
            for cypher in statements:
                try:
                    sess.run(cypher)
                except Exception:
                    pass
        return True
    except Exception:
        return False
