from django.db import models

EVENT_CHAT_MESSAGE = "chat_message"
EVENT_SKILL_EXECUTION = "skill_execution"
EVENT_MEMORY_UPDATE = "memory_update"
EVENT_AGENT_CREATED = "agent_created"
EVENT_AGENT_UPDATED = "agent_updated"
EVENT_AGENT_DELETED = "agent_deleted"
EVENT_SESSION_CREATED = "session_created"
EVENT_SKILL_TOGGLED = "skill_toggled"


class AuditLog(models.Model):
    user = models.ForeignKey("users.UserProfile", on_delete=models.CASCADE, related_name="audit_logs")
    agent = models.ForeignKey("Agent", null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_logs")
    event_type = models.CharField(max_length=64, db_index=True)
    description = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["event_type", "-created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} by {self.user} @ {self.created_at:%Y-%m-%d %H:%M}"
