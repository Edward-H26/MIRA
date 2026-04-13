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


def auto_mark_skill_neo4j(bullet_data: dict) -> None:
    if (
        int(bullet_data.get("memoryType", 0)) == 3
        and float(bullet_data.get("proceduralStrength", 0)) > 60.0
        and not bullet_data.get("isSkill", False)
    ):
        from app.services import neo4j_memory as neo4j
        neo4j.update_bullet(
            str(bullet_data.get("id", "")),
            is_skill=True,
            skill_group="procedural_auto",
        )
