from django.db import transaction
from django.utils import timezone


def enqueue(operation: str, entity_type: str, entity_id: str, payload: dict | None = None) -> None:
    """Write a PENDING OutboxEvent in the current Django transaction.

    Use for UPDATE and DELETE operations whose Neo4j projection is idempotent
    (SET, DETACH DELETE). The drain_outbox worker will replay the event until
    it succeeds, giving eventual consistency even if Neo4j is unreachable.
    """
    from .models.outbox_event import OutboxEvent
    OutboxEvent.objects.create(
        operation=operation,
        entity_type=entity_type,
        entity_id=str(entity_id),
        payload=payload or {},
    )


def enqueue_after_commit(operation: str, entity_type: str, entity_id: str, payload: dict | None = None) -> None:
    """Pending-event variant that uses transaction.on_commit so the
    OutboxEvent is only persisted after the outer transaction commits."""
    def _enqueue():
        enqueue(operation, entity_type, entity_id, payload)
    transaction.on_commit(_enqueue)


def record_applied(operation: str, entity_type: str, entity_id: str, payload: dict | None = None) -> None:
    """Write an APPLIED OutboxEvent - the direct Neo4j call already
    succeeded, we're just persisting the audit record.

    Use for CREATE operations whose naive replay would duplicate the
    entity. The worker skips APPLIED events; this row exists purely as a
    change-stream feed for downstream consumers.
    """
    from .models.outbox_event import OutboxEvent
    OutboxEvent.objects.create(
        operation=operation,
        entity_type=entity_type,
        entity_id=str(entity_id),
        payload=payload or {},
        status=OutboxEvent.STATUS_APPLIED,
        applied_at=timezone.now(),
    )


def record_applied_after_commit(operation: str, entity_type: str, entity_id: str, payload: dict | None = None) -> None:
    """Applied-event variant tied to the current transaction's commit."""
    def _record():
        record_applied(operation, entity_type, entity_id, payload)
    transaction.on_commit(_record)
