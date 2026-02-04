from django.db import models
from django.urls import reverse

class Memory(models.Model):
    """
    Real-world entity: Memory record attached to a user
    Why it exists: Persist long-term memory items for personalization
    """
    # The user this memory belongs to; cascade to avoid orphaned memories
    user = models.ForeignKey("users.User", on_delete=models.CASCADE)
    # Number of access events processed since the component was last retrieved
    access_clock = models.IntegerField()
    # Timestamp when the memory record was created
    created_at = models.DateTimeField(auto_now_add=True)
    # Timestamp when the memory record was last updated
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['updated_at']
        indexes = [models.Index(fields=['user','-access_clock'])]

    def __str__(self):
        return f"{self.user_id} - {self.id}"

    def get_absolute_url(self):
        return reverse("chat:memory_detail", kwargs={"memory_id": self.pk})
