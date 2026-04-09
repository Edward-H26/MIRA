import hashlib

from django.db import models


def user_file_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    content = instance.file.read()
    instance.file.seek(0)
    contentHash = hashlib.sha256(content).hexdigest()[:16]
    return f"users/{instance.user.uuid}/{contentHash}.{ext}"


MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024


class Document(models.Model):
    user = models.ForeignKey("users.UserProfile", on_delete=models.CASCADE, related_name="documents")
    agent = models.ForeignKey("chat.Agent", on_delete=models.CASCADE, null=True, blank=True, related_name="documents")
    filename = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    file = models.FileField(upload_to=user_file_path, null=True, blank=True)
    file_size = models.CharField(max_length=50, blank=True, default="")
    raw_text = models.TextField()
    parsed_fields = models.JSONField(default=dict, blank=True)
    ttl_days = models.IntegerField(default=7, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.filename} ({self.created_at:%Y-%m-%d})"
