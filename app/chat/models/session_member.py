from django.db import models


class SessionMember(models.Model):
    ROLE_ADMIN = "admin"
    ROLE_MEMBER = "member"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Admin"),
        (ROLE_MEMBER, "Member"),
    ]

    session = models.ForeignKey("Session", on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey("users.UserProfile", on_delete=models.CASCADE, related_name="group_memberships")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("session", "user")]
        ordering = ["joined_at"]

    def __str__(self):
        return f"{self.user} in {self.session} ({self.role})"
