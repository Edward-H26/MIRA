from django.db import models
from django.urls import reverse
from django.utils import timezone

# Create your models here.
class Session(models.Model):
    """
    Real-world entity: Chat session belonging to a user
    Why it exists: Group messages into a single conversation context
    """
    # The user who owns this chat session; cascade to remove sessions if the user is deleted
    user = models.ForeignKey("users.UserProfile", on_delete=models.CASCADE, related_name="chat_session")
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

    def get_absolute_url(self):
        return reverse("chat:conversation_detail", kwargs={"session_id": self.pk})

    @classmethod
    def create_with_opening_exchange(cls, user_profile, content, assistant_reply="Agent Response"):
        prompt = (content or "").strip()
        if not prompt:
            return None

        session = cls.objects.create(user=user_profile, title=prompt[:200])

        from .message import Message, Role
        Message.objects.create(session=session, role=Role.USER, content=prompt)
        Message.objects.create(session=session, role=Role.ASSISTANT, content=assistant_reply)

        session.updated_at = timezone.now()
        session.save(update_fields=["updated_at"])
        return session
