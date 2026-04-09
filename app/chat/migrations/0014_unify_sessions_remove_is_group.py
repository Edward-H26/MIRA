from django.db import migrations


def backfill_session_members(apps, schema_editor):
    Session = apps.get_model("chat", "Session")
    SessionMember = apps.get_model("chat", "SessionMember")
    for session in Session.objects.all():
        if not SessionMember.objects.filter(session=session).exists():
            SessionMember.objects.create(
                session=session,
                user=session.user,
                role="admin",
            )


class Migration(migrations.Migration):
    dependencies = [
        ("chat", "0013_ensure_one_agent_per_user"),
    ]

    operations = [
        migrations.RunPython(backfill_session_members, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="session",
            name="is_group",
        ),
    ]
