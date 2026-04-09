from django.db import models
from django.utils.text import slugify


class SkillSource(models.TextChoices):
    TEMPLATE = "template", "Template"
    CUSTOM = "custom", "Custom"
    GENERATED = "generated", "Generated from memories"


class Skill(models.Model):
    user = models.ForeignKey("users.UserProfile", on_delete=models.CASCADE, related_name="skills")
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120)
    description = models.TextField(blank=True, default="")
    content = models.TextField()
    category = models.CharField(max_length=60, blank=True, default="")
    is_enabled = models.BooleanField(default=True)
    source = models.CharField(max_length=20, choices=SkillSource, default=SkillSource.TEMPLATE)
    source_bullet_ids = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "slug"], name="unique_skill_per_user"),
        ]
        ordering = ["-updated_at"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:120] or "skill"
            base = self.slug
            counter = 1
            while Skill.objects.filter(user=self.user, slug=self.slug).exclude(pk=self.pk).exists():
                self.slug = f"{base[:115]}-{counter}"
                counter += 1
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.user})"
