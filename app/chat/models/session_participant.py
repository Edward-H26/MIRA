from django.db import models


class SessionParticipant(models.Model):
    session = models.ForeignKey("Session", on_delete=models.CASCADE, related_name="participants")
    agent = models.ForeignKey("Agent", on_delete=models.CASCADE, related_name="sessions")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("session", "agent")]
