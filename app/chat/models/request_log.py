from django.db import models


class RequestLog(models.Model):
    user = models.ForeignKey(
        "users.UserProfile",
        on_delete=models.CASCADE,
        related_name="request_logs",
    )
    session = models.ForeignKey(
        "Session",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="request_logs",
    )
    request_type = models.CharField(max_length=32, db_index=True, default="chat")
    model_name = models.CharField(max_length=64, default="gemini-3-flash-preview")
    pipeline = models.CharField(max_length=32, default="gemini_direct")
    status = models.CharField(max_length=16, default="success")
    latency_ms = models.IntegerField(default=0)
    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    estimated_cost_usd = models.FloatField(default=0.0)
    error_type = models.CharField(max_length=128, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["model_name", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.request_type} ({self.model_name}) {self.latency_ms}ms @ {self.created_at:%Y-%m-%d %H:%M}"
