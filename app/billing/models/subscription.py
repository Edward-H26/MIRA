from django.db import models

class Status(models.IntegerChoices):
    INCOMPLETE = 0,
    ACTIVE = 1,
    EXPIRED = 2,

class Subscription(models.Model):
    """
    Real-world entity: User subscription to a plan
    Why it exists: Track entitlement, status, and billing periods per user
    """
    # The user who owns this subscription
    user = models.OneToOneField("users.User", on_delete=models.CASCADE)
    # The plan this subscription is for
    plan = models.ForeignKey("Plan", on_delete=models.PROTECT)

    # Current subscription status
    status = models.IntegerField(choices=Status, default=Status.INCOMPLETE)
    # Whether the subscription auto-renews
    auto_renew = models.BooleanField(default=False)

    # Start date of the current billing period
    current_period_start = models.DateField()
    # End date of the current billing period
    current_period_end = models.DateField()

    # Timestamp when this record was last updated
    updated_at = models.DateTimeField(auto_now=True)
    # Timestamp when this record was created
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user_id} - {self.plan}"

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "plan"], name="unique_plan"),
        ]
