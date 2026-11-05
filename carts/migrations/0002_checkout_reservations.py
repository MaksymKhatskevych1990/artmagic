import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


def initialize_order_sequence(apps, schema_editor):
    Order = apps.get_model("carts", "Order")
    Sequence = apps.get_model("carts", "OrderNumberSequence")
    maximum = Order.objects.order_by("-order_number").values_list(
        "order_number", flat=True
    ).first() or 0
    Sequence.objects.create(singleton=1, last_number=maximum)


class Migration(migrations.Migration):

    dependencies = [
        ("carts", "0001_initial"),
        ("products", "0002_alter_category_meta_title"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="updated_at",
            field=models.DateTimeField(
                auto_now=True,
                default=django.utils.timezone.now,
                verbose_name="Оновлено",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="order",
            name="status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "Історичне замовлення"),
                    ("draft", "Чернетка"),
                    ("pending_payment", "Очікує оплату"),
                    ("new", "Нове"),
                    ("paid", "Оплачено"),
                    ("processing", "В обробці"),
                    ("entered_in_1c", "Внесено в 1С"),
                    ("completed", "Завершено"),
                    ("cancelled", "Скасовано"),
                    ("payment_failed", "Помилка оплати"),
                    ("expired", "Час оплати минув"),
                    (
                        "paid_stock_conflict",
                        "Оплачено, потрібна перевірка залишку",
                    ),
                ],
                db_index=True,
                default="",
                max_length=32,
                verbose_name="Статус",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="payment_code",
            field=models.CharField(blank=True, default="", max_length=64, verbose_name="Код оплати"),
        ),
        migrations.AddField(
            model_name="order",
            name="delivery_code",
            field=models.CharField(blank=True, default="", max_length=64, verbose_name="Код доставки"),
        ),
        migrations.AddField(
            model_name="order",
            name="client_request_id",
            field=models.UUIDField(blank=True, null=True, verbose_name="Ключ оформлення"),
        ),
        migrations.AddField(
            model_name="order",
            name="stock_checked_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Перевірка залишку"),
        ),
        migrations.AddField(
            model_name="order",
            name="notifications_sent_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Лист підтвердження"),
        ),
        migrations.AddField(
            model_name="order",
            name="awaiting_notice_sent_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Лист про очікування оплати"),
        ),
        migrations.AddField(
            model_name="order",
            name="paid_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Оплачено"),
        ),
        migrations.AddField(
            model_name="order",
            name="entered_in_1c_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Внесено в 1С"),
        ),
        migrations.AddField(
            model_name="order",
            name="cancelled_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Скасовано"),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.UniqueConstraint(
                condition=models.Q(client_request_id__isnull=False),
                fields=("client_request_id",),
                name="unique_order_client_request_id",
            ),
        ),
        migrations.CreateModel(
            name="OrderNumberSequence",
            fields=[
                (
                    "singleton",
                    models.PositiveSmallIntegerField(
                        default=1,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("last_number", models.PositiveIntegerField(default=0)),
            ],
            options={
                "verbose_name": "Лічильник замовлень",
                "verbose_name_plural": "Лічильник замовлень",
            },
        ),
        migrations.RunPython(
            initialize_order_sequence,
            migrations.RunPython.noop,
        ),
        migrations.CreateModel(
            name="StockReservation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.PositiveIntegerField(verbose_name="Кількість")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending_payment", "Очікує оплату"),
                            ("active", "Активний"),
                            (
                                "pending_1c_reconciliation",
                                "Очікує вивантаження 1С",
                            ),
                            ("reconciled", "Узгоджено з 1С"),
                            ("released", "Звільнено"),
                            ("expired", "Прострочено"),
                        ],
                        db_index=True,
                        default="active",
                        max_length=32,
                        verbose_name="Статус",
                    ),
                ),
                ("expires_at", models.DateTimeField(blank=True, db_index=True, null=True, verbose_name="Діє до")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("released_at", models.DateTimeField(blank=True, null=True, verbose_name="Звільнено")),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reservations", to="carts.order", verbose_name="Замовлення")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stock_reservations", to="products.products", verbose_name="Товар")),
            ],
            options={
                "verbose_name": "Резерв",
                "verbose_name_plural": "Резерви",
            },
        ),
        migrations.AddConstraint(
            model_name="stockreservation",
            constraint=models.UniqueConstraint(fields=("order", "product"), name="unique_reservation_order_product"),
        ),
        migrations.CreateModel(
            name="OrderStatusLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("old_status", models.CharField(blank=True, default="", max_length=32)),
                ("new_status", models.CharField(blank=True, default="", max_length=32)),
                ("actor", models.CharField(blank=True, default="", max_length=150)),
                ("comment", models.TextField(blank=True, default="")),
                ("changed_at", models.DateTimeField(auto_now_add=True)),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="status_logs", to="carts.order", verbose_name="Замовлення")),
            ],
            options={
                "verbose_name": "Зміна статусу",
                "verbose_name_plural": "Журнал статусів",
                "ordering": ["-changed_at"],
            },
        ),
        migrations.CreateModel(
            name="OrderNotificationDelivery",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("awaiting_payment", "Очікує оплату"),
                            ("confirmation", "Підтвердження"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "recipient_type",
                    models.CharField(
                        choices=[("shop", "Магазин"), ("customer", "Покупець")],
                        max_length=16,
                    ),
                ),
                ("recipient", models.EmailField(max_length=254)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Очікує"),
                            ("sending", "Надсилається"),
                            ("sent", "Надіслано"),
                            ("failed", "Помилка"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("last_error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notification_deliveries",
                        to="carts.order",
                    ),
                ),
            ],
            options={
                "verbose_name": "Доставка листа",
                "verbose_name_plural": "Доставка листів",
            },
        ),
        migrations.AddConstraint(
            model_name="ordernotificationdelivery",
            constraint=models.UniqueConstraint(
                fields=("order", "kind", "recipient_type"),
                name="unique_order_notification_recipient",
            ),
        ),
    ]
