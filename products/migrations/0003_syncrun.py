from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0002_alter_category_meta_title"),
    ]

    operations = [
        migrations.CreateModel(
            name="SyncRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sync_id", models.UUIDField(unique=True)),
                ("started_at", models.DateTimeField()),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("success_count", models.PositiveIntegerField(default=0)),
                ("error_count", models.PositiveIntegerField(default=0)),
                ("status", models.CharField(default="failed", max_length=32)),
                ("message", models.TextField(blank=True, default="")),
            ],
            options={
                "verbose_name": "Синхронізація 1С",
                "verbose_name_plural": "Синхронізації 1С",
                "ordering": ["-started_at"],
            },
        ),
    ]
