from django.db import models


class Document(models.Model):
    user = models.ForeignKey("users.UserProfile", on_delete=models.CASCADE, related_name="documents")
    agent = models.ForeignKey("chat.Agent", on_delete=models.CASCADE, null=True, blank=True, related_name="documents")
    filename = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    file = models.FileField(upload_to="agent_documents/", null=True, blank=True)
    file_size = models.CharField(max_length=50, blank=True, default="")
    raw_text = models.TextField()
    parsed_fields = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.filename} ({self.created_at:%Y-%m-%d})"
