import time

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = (
        "Drain pending OutboxEvent rows into Neo4j. Reads pending events FIFO, "
        "applies them, marks as applied on success or failed after max attempts. "
        "Intended to run as a long-lived worker (--loop) or one-shot batch."
    )

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=50, help="Events per batch.")
        parser.add_argument("--max-attempts", type=int, default=5, help="Give up after N failures.")
        parser.add_argument("--loop", action="store_true", help="Keep draining forever (1s sleep between empty batches).")
        parser.add_argument("--once", action="store_true", help="Process a single batch and exit.")

    def handle(self, *args, **options):
        from app.chat.models.outbox_event import OutboxEvent

        batchSize = max(1, int(options.get("batch_size") or 50))
        maxAttempts = max(1, int(options.get("max_attempts") or 5))
        loop = bool(options.get("loop"))
        once = bool(options.get("once")) or not loop

        while True:
            processed = self._drain_batch(OutboxEvent, batchSize, maxAttempts)
            if once:
                self.stdout.write(self.style.SUCCESS(f"Processed {processed} event(s). Exiting."))
                return
            if processed == 0:
                time.sleep(1.0)

    def _drain_batch(self, OutboxEvent, batchSize, maxAttempts):
        events = list(
            OutboxEvent.objects.filter(status=OutboxEvent.STATUS_PENDING)
            .order_by("created_at")[:batchSize]
        )
        if not events:
            return 0
        processed = 0
        for ev in events:
            try:
                self._apply(ev)
                with transaction.atomic():
                    ev.status = OutboxEvent.STATUS_APPLIED
                    ev.applied_at = timezone.now()
                    ev.last_error = ""
                    ev.save(update_fields=["status", "applied_at", "last_error", "updated_at"])
                processed += 1
            except Exception as exc:
                ev.attempts = (ev.attempts or 0) + 1
                ev.last_error = str(exc)[:500]
                ev.status = (
                    OutboxEvent.STATUS_FAILED if ev.attempts >= maxAttempts else OutboxEvent.STATUS_PENDING
                )
                ev.save(update_fields=["attempts", "last_error", "status", "updated_at"])
                self.stdout.write(self.style.WARNING(
                    f"  event={ev.pk} op={ev.operation} attempt={ev.attempts} "
                    f"status={ev.status} error={ev.last_error[:100]}"
                ))
        return processed

    def _apply(self, event):
        """Project one OutboxEvent into Neo4j.

        Handler policy:
        - CREATE events should never reach this code path. Callers must emit
          them via `outbox.record_applied` (status=APPLIED at enqueue). A
          defensive no-op is kept here for robustness.
        - UPDATE / DELETE handlers MUST be idempotent (SET, DETACH DELETE).
        """
        from app.services import neo4j_memory as neo4j

        op = event.operation
        payload = event.payload or {}

        if op in {"agent.create", "session.create", "message.create", "document.create", "notification.create"}:
            return

        if op == "user.upsert":
            neo4j.create_or_update_django_user(
                user_id=str(event.entity_id),
                username=payload.get("username", ""),
                email=payload.get("email", ""),
                password_hash=payload.get("password_hash", ""),
                display_name=payload.get("display_name", ""),
                is_active=bool(payload.get("is_active", True)),
                is_staff=bool(payload.get("is_staff", False)),
                is_superuser=bool(payload.get("is_superuser", False)),
                first_name=payload.get("first_name", ""),
                last_name=payload.get("last_name", ""),
                uuid=payload.get("uuid", ""),
            )
            return

        if op == "user.delete_cascade":
            neo4j.delete_user_cascade(str(event.entity_id))
            return

        if op == "agent.update":
            neo4j.update_agent(str(event.entity_id), **(payload.get("fields") or {}))
            return

        if op == "agent.delete":
            neo4j.delete_agent(str(event.entity_id))
            return

        if op == "session.update":
            neo4j.update_session(str(event.entity_id), **(payload.get("fields") or {}))
            return

        if op == "session.delete":
            neo4j.delete_session(str(event.entity_id))
            return

        if op == "notification.update":
            fields = payload.get("fields") or {}
            if "markRead" in fields:
                neo4j.mark_notification_read(str(event.entity_id))
            return

        raise RuntimeError(f"Unknown outbox operation: {op!r}")
