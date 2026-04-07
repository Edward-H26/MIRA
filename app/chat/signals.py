from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender="chat.MemoryBullet")
def autoMarkSkill(sender, instance, **kwargs):
    if (
        instance.memory_type == 3
        and float(instance.procedural_strength or 0) > 60.0
        and not instance.is_skill
    ):
        from app.chat.models.memory_bullet import MemoryBullet

        MemoryBullet.objects.filter(pk=instance.pk).update(
            is_skill=True, skill_group="procedural_auto"
        )
