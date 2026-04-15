"""Transactional wrappers around Neo4j writes that also emit OutboxEvent rows.

Every write path that used to call ``neo4j.create_session`` / ``update_session``
/ ``delete_session`` directly should migrate here. The wrappers:

1. Open a Django @transaction.atomic block.
2. Perform the direct Neo4j write for immediate-consistency user feedback.
3. Emit an OutboxEvent inside the same transaction (pending for UPDATE/DELETE,
   pre-applied for CREATE to avoid duplicate replays).

The Django transaction gives us rollback-on-failure for the outbox event; the
idempotent Neo4j SET/DETACH DELETE semantics make worker replays safe.
"""
from django.db import transaction

from app.services import neo4j_memory as neo4j
from . import outbox


def create_session_with_outbox(user_id: str, title: str) -> dict:
    with transaction.atomic():
        sessionData = neo4j.create_session(str(user_id), title)
        sessionId = str(sessionData.get("id", "")) if sessionData else ""
        if sessionId:
            outbox.record_applied_after_commit(
                operation="session.create",
                entity_type="Session",
                entity_id=sessionId,
                payload={"user_id": str(user_id), "title": title},
            )
    return sessionData or {}


def update_session_with_outbox(session_id: str, **fields) -> dict | None:
    if not fields:
        return neo4j.get_session_by_id(str(session_id))
    with transaction.atomic():
        updated = neo4j.update_session(str(session_id), **fields)
        outbox.enqueue_after_commit(
            operation="session.update",
            entity_type="Session",
            entity_id=str(session_id),
            payload={"fields": dict(fields)},
        )
    return updated


def delete_session_with_outbox(session_id: str) -> None:
    with transaction.atomic():
        neo4j.delete_session(str(session_id))
        outbox.enqueue_after_commit(
            operation="session.delete",
            entity_type="Session",
            entity_id=str(session_id),
            payload={},
        )


def create_message_with_outbox(
    session_id: str,
    content: str,
    created_by: str,
    role: str = "user",
    sender_agent_id: str | None = None,
    sender_agent_name: str = "",
    is_ai: bool = False,
) -> dict:
    with transaction.atomic():
        msg = neo4j.create_message(
            session_id=str(session_id),
            content=content,
            created_by=str(created_by),
            role=role,
            sender_agent_id=sender_agent_id,
            sender_agent_name=sender_agent_name,
            is_ai=is_ai,
        )
        msgId = str(msg.get("id", "")) if msg else ""
        if msgId:
            outbox.record_applied_after_commit(
                operation="message.create",
                entity_type="Message",
                entity_id=msgId,
                payload={
                    "session_id": str(session_id),
                    "role": role,
                    "is_ai": is_ai,
                    "created_by": str(created_by),
                },
            )
    return msg or {}
