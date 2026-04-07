from django.db import models
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
import os
from datetime import timedelta

# Create your models here.
class Session(models.Model):
    """
    Real-world entity: Chat session belonging to a user (or a group)
    Why it exists: Group messages into a single conversation context
    """
    user = models.ForeignKey("users.UserProfile", on_delete=models.CASCADE, related_name="chat_session")
    title = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    generation_in_progress = models.BooleanField(default=False)
    generation_started_at = models.DateTimeField(null=True, blank=True)
    is_group = models.BooleanField(default=False)
    access_key = models.CharField(max_length=50, unique=True, null=True, blank=True)
    description = models.TextField(blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["user", "-created_at"])]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user_id} - {self.title or 'Untitled'}"

    def get_absolute_url(self):
        return reverse("chat:conversation_detail", kwargs={"session_id": self.pk})

    @staticmethod
    def _lock_timeout_seconds():
        raw = os.getenv("CHAT_GENERATION_LOCK_TIMEOUT_SECONDS", "180")
        try:
            value = int(raw)
        except Exception:
            value = 180
        return value if value > 0 else 180

    def _is_lock_stale(self):
        if not self.generation_in_progress:
            return False
        if not self.generation_started_at:
            return False
        return self.generation_started_at <= timezone.now() - timedelta(seconds=self._lock_timeout_seconds())

    def ensure_generation_lock_fresh(self):
        if not self._is_lock_stale():
            return bool(self.generation_in_progress)
        self.generation_in_progress = False
        self.generation_started_at = None
        self.save(update_fields=["generation_in_progress", "generation_started_at"])
        return False

    def acquire_generation_lock(self):
        with transaction.atomic():
            row = Session.objects.select_for_update().get(pk=self.pk)
            if row._is_lock_stale():
                row.generation_in_progress = False
                row.generation_started_at = None
            if row.generation_in_progress:
                return False
            row.generation_in_progress = True
            row.generation_started_at = timezone.now()
            row.save(update_fields=["generation_in_progress", "generation_started_at"])
        self.generation_in_progress = True
        self.generation_started_at = timezone.now()
        return True

    def release_generation_lock(self):
        Session.objects.filter(pk=self.pk).update(
            generation_in_progress=False,
            generation_started_at=None,
        )
        self.generation_in_progress = False
        self.generation_started_at = None

    @classmethod
    def create_with_opening_exchange(cls, user_profile, content, assistant_reply="Agent Response"):
        prompt = (content or "").strip()
        if not prompt:
            return None

        session = cls.objects.create(user=user_profile, title=prompt[:200])

        from .message import Message, Role
        try:
            from app.chat.service import build_agent_reply_from_stream

            ai_text = build_agent_reply_from_stream(prompt)
        except Exception:
            ai_text = assistant_reply
        Message.objects.create(session=session, role=Role.USER, content=prompt)
        Message.objects.create(session=session, role=Role.ASSISTANT, content=ai_text)

        session.updated_at = timezone.now()
        session.save(update_fields=["updated_at"])
        return session
