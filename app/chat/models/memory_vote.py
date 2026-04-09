from django.db import models


class VoteValue(models.IntegerChoices):
    DISLIKE = -1, "Dislike"
    LIKE = 1, "Like"


class MemoryVote(models.Model):
    user = models.ForeignKey("users.UserProfile", on_delete=models.CASCADE, related_name="memory_votes")
    bullet = models.ForeignKey("chat.MemoryBullet", on_delete=models.CASCADE, related_name="votes")
    value = models.SmallIntegerField(choices=VoteValue)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "bullet"], name="unique_vote_per_user_bullet"),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        label = "Like" if self.value == VoteValue.LIKE else "Dislike"
        return f"{self.user} {label} bullet #{self.bullet_id}"
