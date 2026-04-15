from django.db import models


class OutboxEvent(models.Model):
    """Transactional-outbox queue for Django -> Neo4j projection.

    Writers insert an OutboxEvent inside the same Django transaction that
    mutates the canonical Postgres row. A separate worker drains the table,
    applies the projection to Neo4j, and flips status to 'applied'.

    This gives eventual consistency with exactly-once delivery even if Neo4j
    is unavailable at the time of the Django write. If Neo4j is down for
    hours, writes keep succeeding in Django and the outbox catches up when
    the graph is reachable again.
    """

    STATUS_PENDING = "pending"
    STATUS_APPLIED = "applied"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_PENDING, "pending"),
        (STATUS_APPLIED, "applied"),
        (STATUS_FAILED, "failed"),
    )

    operation = models.CharField(max_length=64)
    entity_type = models.CharField(max_length=32)
    entity_id = models.CharField(max_length=64)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    attempts = models.IntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["entity_type", "entity_id"]),
        ]
        ordering = ["created_at"]

    def __str__(self):
        return f"OutboxEvent({self.operation} {self.entity_type} {self.entity_id} {self.status})"
