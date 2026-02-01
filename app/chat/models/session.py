from django.db import models

# Create your models here.
class Session(models.Model):
    """
    Real-world entity: Chat session belonging to a user
    Why it exists: Group messages into a single conversation context
    """
    # The user who owns this chat session; cascade to remove sessions if the user is deleted
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="chat_session")
    # Session title displayed in the UI
    title = models.CharField(max_length=200, blank=True, default="")
    # Timestamp when the session was created
    created_at = models.DateTimeField(auto_now_add=True)
    # Timestamp when the session was last updated
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["user", "-created_at"])]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user_id} - {self.title or 'Untitled'}"
