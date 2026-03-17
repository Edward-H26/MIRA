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

    from neo4j import GraphDatabase

    with _DRIVER_LOCK:
        if _DRIVER is None:
            _DRIVER = GraphDatabase.driver(uri, auth=(user, password))
    return _DRIVER


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
