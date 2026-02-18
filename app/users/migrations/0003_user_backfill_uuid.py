import uuid

from django.db import migrations


def backfill_user_uuid(apps, schema_editor):
    User = apps.get_model("users", "User")
    for profile in User.objects.filter(uuid__isnull=True).iterator():
        value = uuid.uuid4()
        while User.objects.filter(uuid=value).exists():
            value = uuid.uuid4()
        profile.uuid = value
        profile.save(update_fields=["uuid"])


def noop_reverse(apps, schema_editor):
    # UUID backfill is intentionally irreversible.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0002_user_add_uuid_nullable"),
    ]

    operations = [
        migrations.RunPython(backfill_user_uuid, reverse_code=noop_reverse),
    ]

