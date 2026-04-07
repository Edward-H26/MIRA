from django.db import models


class Agent(models.Model):
    user = models.ForeignKey("users.UserProfile", on_delete=models.CASCADE, related_name="agents")
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default="")
    avatar = models.ImageField(null=True, blank=True, upload_to="avatars/agents/")
    is_active = models.BooleanField(default=True)
    system_prompt = models.TextField(blank=True, default="")
    temperature = models.FloatField(default=0.7)
    max_tokens = models.IntegerField(default=1024)
    configuration = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["user", "-created_at"])]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.user})"
