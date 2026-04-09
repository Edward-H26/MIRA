from django.db import migrations, models
import app.chat.models.document


class Migration(migrations.Migration):
    dependencies = [
        ("chat", "0014_unify_sessions_remove_is_group"),
    ]

    operations = [
        migrations.AlterField(
            model_name="document",
            name="file",
            field=models.FileField(
                blank=True,
                null=True,
                upload_to=app.chat.models.document.user_file_path,
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="ttl_days",
            field=models.IntegerField(blank=True, default=7, null=True),
        ),
    ]
