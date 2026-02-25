from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0005_rename_user_userprofile_alter_userprofile_table"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="display_name",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
    ]
