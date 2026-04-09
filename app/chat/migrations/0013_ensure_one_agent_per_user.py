from django.db import migrations


def create_default_agents(apps, schema_editor):
    UserProfile = apps.get_model("users", "UserProfile")
    Agent = apps.get_model("chat", "Agent")
    for profile in UserProfile.objects.all():
        if not Agent.objects.filter(user=profile).exists():
            Agent.objects.create(
                user=profile,
                name="My Assistant",
                temperature=0.7,
                max_tokens=1024,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("chat", "0012_fix_ttl_days_default"),
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_default_agents, migrations.RunPython.noop),
    ]
