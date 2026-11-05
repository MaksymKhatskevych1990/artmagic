from django.utils import timezone
from django.db import models, transaction, IntegrityError
from products.models import Products
from users.models import CustomUser


class CartQueryset(models.QuerySet):

    def total_price(self):
        return sum(cart.products_price() for cart in self)

    def total_quantity(self):
        if self:
            return sum(cart.quantity for cart in self)
        return 0


class Cart(models.Model):
    user = models.ForeignKey(to=CustomUser, on_delete=models.CASCADE, blank=True, null=True,
                             verbose_name='Пользователь')
    product = models.ForeignKey(to=Products, on_delete=models.CASCADE, verbose_name='Товар')
    quantity = models.PositiveSmallIntegerField(default=0, verbose_name='Количество')
    session_key = models.CharField(max_length=32, null=True, blank=True)
    created_timestamp = models.DateTimeField(auto_now_add=True, verbose_name='Дата добавления')

    class Meta:
        db_table = 'cart'
        verbose_name = "Корзина"
        verbose_name_plural = "Корзина"

    objects = CartQueryset().as_manager()

    def products_price(self):
        return round(self.product.sell_price() * self.quantity, 2)

    def __str__(self):
        if self.user:
            return f'Корзина {self.user.username} | Товар {self.product.name} | Количество {self.quantity}'

        return f'Анонимная корзина | Товар {self.product.name} | Количество {self.quantity}'


class Order(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_PENDING_PAYMENT = "pending_payment"
    STATUS_NEW = "new"
    STATUS_PAID = "paid"
    STATUS_PROCESSING = "processing"
    STATUS_ENTERED_IN_1C = "entered_in_1c"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_PAYMENT_FAILED = "payment_failed"
    STATUS_EXPIRED = "expired"
    STATUS_PAID_STOCK_CONFLICT = "paid_stock_conflict"
    STATUS_CHOICES = [
        ("", "Історичне замовлення"),
        (STATUS_DRAFT, "Чернетка"),
        (STATUS_PENDING_PAYMENT, "Очікує оплату"),
        (STATUS_NEW, "Нове"),
        (STATUS_PAID, "Оплачено"),
        (STATUS_PROCESSING, "В обробці"),
        (STATUS_ENTERED_IN_1C, "Внесено в 1С"),
        (STATUS_COMPLETED, "Завершено"),
        (STATUS_CANCELLED, "Скасовано"),
        (STATUS_PAYMENT_FAILED, "Помилка оплати"),
        (STATUS_EXPIRED, "Час оплати минув"),
        (STATUS_PAID_STOCK_CONFLICT, "Оплачено, потрібна перевірка залишку"),
    ]

    user = models.ForeignKey(
        to=CustomUser,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        verbose_name='Користувач'  # User
    )
    order_number = models.PositiveIntegerField(
        unique=True,
        editable=False,
        verbose_name='№ замовлення'  # Order Number
    )
    name = models.CharField(
        max_length=255,
        verbose_name='ПІБ'  # Name
    )
    phone = models.CharField(
        max_length=20,
        verbose_name='Телефон'  # Phone
    )
    email = models.EmailField(
        verbose_name='Email'  # Email
    )
    payment = models.CharField(
        max_length=50,
        verbose_name='Спосіб оплати'  # Payment Method
    )
    address = models.TextField(
        verbose_name='Адреса'  # Address
    )
    total_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='Загальна сума'  # Total Price
    )
    products = models.JSONField(
        verbose_name='Продукти'  # Products
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата створення'  # Created At
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Оновлено")
    status = models.CharField(
        max_length=32,
        blank=True,
        default="",
        choices=STATUS_CHOICES,
        db_index=True,
        verbose_name="Статус",
    )
    payment_code = models.CharField(max_length=64, blank=True, default="", verbose_name="Код оплати")
    delivery_code = models.CharField(max_length=64, blank=True, default="", verbose_name="Код доставки")
    client_request_id = models.UUIDField(null=True, blank=True, verbose_name="Ключ оформлення")
    stock_checked_at = models.DateTimeField(null=True, blank=True, verbose_name="Перевірка залишку")
    notifications_sent_at = models.DateTimeField(null=True, blank=True, verbose_name="Лист підтвердження")
    awaiting_notice_sent_at = models.DateTimeField(null=True, blank=True, verbose_name="Лист про очікування оплати")
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name="Оплачено")
    entered_in_1c_at = models.DateTimeField(null=True, blank=True, verbose_name="Внесено в 1С")
    cancelled_at = models.DateTimeField(null=True, blank=True, verbose_name="Скасовано")

    class Meta:
        verbose_name = 'Замовлення'  # Singular name
        verbose_name_plural = 'Замовлення'  # Plural name
        ordering = ['-created_at']  # Optionally add default ordering
        constraints = [
            models.UniqueConstraint(
                fields=["client_request_id"],
                condition=models.Q(client_request_id__isnull=False),
                name="unique_order_client_request_id",
            ),
        ]

    def __str__(self):
        return f"Order {self.order_number} by {self.name}"

    # другие поля для заказа

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self.generate_order_number()
        super(Order, self).save(*args, **kwargs)

    @classmethod
    def generate_order_number(cls):
        return OrderNumberSequence.next_number()

    def set_status(self, new_status, actor="", comment=""):
        old_status = self.status
        if old_status == new_status:
            return
        self.status = new_status
        self.save(update_fields=["status", "updated_at"])
        OrderStatusLog.objects.create(
            order=self,
            old_status=old_status,
            new_status=new_status,
            actor=actor or "",
            comment=comment or "",
        )


class PreOrder(models.Model):
    user = models.ForeignKey(
        to=CustomUser,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        verbose_name='Користувач'  # User
    )
    order = models.ForeignKey(
        to=Order,
        on_delete=models.CASCADE,
        related_name='preorders',
        verbose_name='Замовлення',
        null=True  # Order
    )
    name = models.CharField(
        max_length=255,
        verbose_name='ПІБ'  # Name
    )
    order_number = models.PositiveIntegerField(
        unique=True,
        editable=False,
        verbose_name='№ замовлення'
    )# Order Number

    products = models.JSONField(
        verbose_name='Продукти'  # Products
    )
    quantity = models.PositiveIntegerField(
        verbose_name='Кількість'  # Quantity of preordered items
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата створення'  # Created At
    )

    class Meta:
        verbose_name = 'Предзамовлення'  # Singular name
        verbose_name_plural = 'Предзамовлення'  # Plural name
        ordering = ['-created_at']  # Optionally add default ordering

    def __str__(self):
        return f"Предзамовлення {self.order_number}"

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self.generate_order_number()
        super(PreOrder, self).save(*args, **kwargs)

    @classmethod
    def generate_order_number(cls):
        with transaction.atomic():
            last_order = cls.objects.select_for_update().order_by('-order_number').first()
            return 1 if last_order is None else last_order.order_number + 1


class StockReservation(models.Model):
    STATUS_PENDING_PAYMENT = "pending_payment"
    STATUS_ACTIVE = "active"
    STATUS_PENDING_1C = "pending_1c_reconciliation"
    STATUS_RECONCILED = "reconciled"
    STATUS_RELEASED = "released"
    STATUS_EXPIRED = "expired"
    HOLDING_STATUSES = (
        STATUS_PENDING_PAYMENT,
        STATUS_ACTIVE,
        STATUS_PENDING_1C,
    )
    STATUS_CHOICES = [
        (STATUS_PENDING_PAYMENT, "Очікує оплату"),
        (STATUS_ACTIVE, "Активний"),
        (STATUS_PENDING_1C, "Очікує вивантаження 1С"),
        (STATUS_RECONCILED, "Узгоджено з 1С"),
        (STATUS_RELEASED, "Звільнено"),
        (STATUS_EXPIRED, "Прострочено"),
    ]

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="reservations", verbose_name="Замовлення")
    product = models.ForeignKey(Products, on_delete=models.PROTECT, related_name="stock_reservations", verbose_name="Товар")
    quantity = models.PositiveIntegerField(verbose_name="Кількість")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True, verbose_name="Статус")
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name="Діє до")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    released_at = models.DateTimeField(null=True, blank=True, verbose_name="Звільнено")

    class Meta:
        verbose_name = "Резерв"
        verbose_name_plural = "Резерви"
        constraints = [
            models.UniqueConstraint(fields=["order", "product"], name="unique_reservation_order_product"),
        ]

    def __str__(self):
        return f"{self.order_id} / {self.product_id} / {self.quantity} / {self.status}"


class OrderNumberSequence(models.Model):
    """Single locked row used to allocate order numbers without races."""

    singleton = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Лічильник замовлень"
        verbose_name_plural = "Лічильник замовлень"

    @classmethod
    def next_number(cls):
        with transaction.atomic():
            sequence, _ = cls.objects.select_for_update().get_or_create(
                singleton=1,
                defaults={
                    "last_number": Order.objects.aggregate(
                        maximum=models.Max("order_number")
                    )["maximum"] or 0,
                },
            )
            current_maximum = Order.objects.aggregate(
                maximum=models.Max("order_number")
            )["maximum"] or 0
            sequence.last_number = max(
                sequence.last_number,
                current_maximum,
            ) + 1
            sequence.save(update_fields=["last_number"])
            return sequence.last_number


class OrderStatusLog(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="status_logs", verbose_name="Замовлення")
    old_status = models.CharField(max_length=32, blank=True, default="")
    new_status = models.CharField(max_length=32, blank=True, default="")
    actor = models.CharField(max_length=150, blank=True, default="")
    comment = models.TextField(blank=True, default="")
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Зміна статусу"
        verbose_name_plural = "Журнал статусів"
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.order_id}: {self.old_status} -> {self.new_status}"


class OrderNotificationDelivery(models.Model):
    KIND_AWAITING_PAYMENT = "awaiting_payment"
    KIND_CONFIRMATION = "confirmation"
    KIND_CHOICES = [
        (KIND_AWAITING_PAYMENT, "Очікує оплату"),
        (KIND_CONFIRMATION, "Підтвердження"),
    ]
    RECIPIENT_SHOP = "shop"
    RECIPIENT_CUSTOMER = "customer"
    RECIPIENT_CHOICES = [
        (RECIPIENT_SHOP, "Магазин"),
        (RECIPIENT_CUSTOMER, "Покупець"),
    ]
    STATUS_PENDING = "pending"
    STATUS_SENDING = "sending"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Очікує"),
        (STATUS_SENDING, "Надсилається"),
        (STATUS_SENT, "Надіслано"),
        (STATUS_FAILED, "Помилка"),
    ]

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="notification_deliveries",
    )
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    recipient_type = models.CharField(max_length=16, choices=RECIPIENT_CHOICES)
    recipient = models.EmailField()
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Доставка листа"
        verbose_name_plural = "Доставка листів"
        constraints = [
            models.UniqueConstraint(
                fields=["order", "kind", "recipient_type"],
                name="unique_order_notification_recipient",
            ),
        ]