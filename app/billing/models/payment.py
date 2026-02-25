from django.db import models

class Status(models.IntegerChoices):
    PENDING = 1,
    SUCCEEDED = 2,
    FAILED = 3,
    CANCELLED = 4,

class Payment(models.Model):
    """
    Real-world entity: Payment transaction for a plan
    Why it exists: Record payment attempts and outcomes for billing
    """
    # The user who made the payment; cascade to remove payments if the user is deleted
    user = models.ForeignKey("users.UserProfile", on_delete=models.CASCADE)
    # Related subscription for this payment; keep payment history if subscription is removed
    subscription = models.ForeignKey("Subscription", on_delete=models.SET_NULL, null=True, blank=True, related_name="payments")
    # Plan being paid for; keep payment history if the plan is removed
    plan = models.ForeignKey("Plan", on_delete=models.SET_NULL, null=True, blank=True)

    # Amount paid in cents
    amount_cents = models.PositiveIntegerField()
    # ISO currency code for the amount
    currency = models.CharField(max_length=10, default="USD")
    # Payment status
    status = models.IntegerField(choices=Status, default=Status.PENDING)

    # Timestamp when the payment was completed
    paid_at = models.DateTimeField(null=True, blank=True)

    # Timestamp when this payment record was created
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-created_at"])
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user_id} {self.amount_cents}{self.currency} {self.status}"

