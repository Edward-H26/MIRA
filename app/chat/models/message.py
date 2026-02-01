from django.db import models

class Role(models.IntegerChoices):
    SYSTEM = 1,
    USER = 2,
    ASSISTANT = 3

class Message(models.Model):
    """
    Real-world entity: Single chat message in a session
    Why it exists: Store conversational turns with roles and timestamps
    """
    # The session this message belongs to; cascade to remove messages with the session
    session = models.ForeignKey("Session", on_delete=models.CASCADE, related_name="messages")
    # The role of the sender such as system or user or assistant
    role = models.SmallIntegerField(choices=Role)
    # Message text content
    content = models.TextField()

    # Timestamp when the message was created
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["session", "created_at"])
        ]
        ordering = ["session","-created_at"]

    def __str__(self):
        return f"{self.session} - {self.role} @ {self.created_at:%Y-%m-%d %H:%M}"
