import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("liqpay_app", "0001_initial"),
        ("carts", "0002_checkout_reservations"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="payment",
            name="user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="payment",
            name="checkout_order",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="liqpay_payment",
                to="carts.order",
            ),
        ),
        migrations.AddField(
            model_name="payment",
            name="liqpay_order_id",
            field=models.CharField(blank=True, max_length=100, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="callback_summary",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="last_callback_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
