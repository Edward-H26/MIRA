from django.db import models

class Interval(models.IntegerChoices):
    MONTHLY = 0,
    YEARLY = 1

class Plan(models.Model):
    """
    Real-world entity: Subscription plan
    Why it exists: Define billable offerings users can subscribe to
    """
    # Human-readable plan name
    name = models.CharField(max_length=100)
    # Short unique code for the plan
    code = models.SlugField(max_length=32)
    # Detailed description of the plan
    description = models.TextField()

    # Billing interval for the plan
    interval = models.PositiveIntegerField(choices=Interval)
    # Price in cents
    price_cents = models.PositiveIntegerField()
    # ISO currency code for the price
    currency = models.CharField(max_length=10, default='USD')

    # Whether the plan is currently available for purchase
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["code", "interval"], name="unique_plan_code_interval"),
        ]
        ordering = ["name", "code", "interval"]

    def __str__(self):
        return f"{self.name} ({self.interval})"
