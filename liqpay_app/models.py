from django.db import models
from users.models import CustomUser


class Payment(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    checkout_order = models.OneToOneField(
        "carts.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="liqpay_payment",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    order_id = models.CharField(max_length=100, unique=True)
    liqpay_order_id = models.CharField(max_length=100, null=True, blank=True, unique=True)
    status = models.CharField(max_length=20, default='pending')
    callback_summary = models.JSONField(null=True, blank=True)
    last_callback_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Payment {self.order_id} - {self.amount} - {self.status}"
