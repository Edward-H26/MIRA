from django.db import models


class NotificationType(models.IntegerChoices):
    AGENT_RESPONSE = 1
    SKILL_GENERATED = 2
    MEMORY_THRESHOLD = 3
    SYSTEM_ALERT = 4


class Notification(models.Model):
    user = models.ForeignKey("users.UserProfile", on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True, default="")
    notification_type = models.SmallIntegerField(choices=NotificationType)
    is_read = models.BooleanField(default=False, db_index=True)
    related_url = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "is_read", "-created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} for {self.user}"
