import json

from django.contrib import admin
from django.shortcuts import render
from django.utils.html import escape
from django.utils.safestring import mark_safe

from carts.checkout import cancel_order, mark_entered_in_1c, send_order_notifications
from carts.models import (
    Cart,
    Order,
    OrderNotificationDelivery,
    OrderStatusLog,
    PreOrder,
    StockReservation,
)


class HasPreorderFilter(admin.SimpleListFilter):
    title = "передзамовлення"
    parameter_name = "has_preorder"

    def lookups(self, request, model_admin):
        return (("yes", "Є передзамовлення"), ("no", "Без передзамовлення"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(preorders__isnull=False).distinct()
        if self.value() == "no":
            return queryset.filter(preorders__isnull=True)
        return queryset


class ReservationInline(admin.TabularInline):
    model = StockReservation
    extra = 0
    can_delete = False
    readonly_fields = ("product", "quantity", "status", "expires_at", "created_at", "released_at")

    def has_add_permission(self, request, obj=None):
        return False


class StatusLogInline(admin.TabularInline):
    model = OrderStatusLog
    extra = 0
    can_delete = False
    readonly_fields = ("old_status", "new_status", "actor", "comment", "changed_at")

    def has_add_permission(self, request, obj=None):
        return False


class NotificationInline(admin.TabularInline):
    model = OrderNotificationDelivery
    extra = 0
    can_delete = False
    readonly_fields = (
        "kind",
        "recipient_type",
        "recipient",
        "status",
        "attempts",
        "last_error",
        "sent_at",
        "updated_at",
    )

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_number", "status", "user", "name", "phone", "email", "payment",
        "total_price", "created_at", "entered_in_1c_at", "display_products",
    )
    list_filter = ("status", "payment", HasPreorderFilter, "created_at")
    date_hierarchy = "created_at"
    search_fields = ("order_number", "name", "phone", "email", "client_request_id")
    inlines = (ReservationInline, NotificationInline, StatusLogInline)
    actions = ("mark_entered_in_1c", "cancel_and_release", "resend_order_email")
    readonly_fields = (
        "display_products", "display_reservations", "order_number", "client_request_id",
        "stock_checked_at", "notifications_sent_at", "awaiting_notice_sent_at",
        "paid_at", "entered_in_1c_at", "cancelled_at", "created_at", "updated_at",
    )
    fieldsets = (
        (None, {"fields": (
            "order_number", "status", "user", "name", "phone", "email", "payment",
            "payment_code", "delivery_code", "address", "total_price", "created_at", "updated_at",
        )}),
        ("Перевірка залишку", {"fields": (
            "stock_checked_at", "client_request_id", "notifications_sent_at",
            "awaiting_notice_sent_at", "paid_at",
        )}),
        ("1С", {
            "description": (
                "Після того як замовлення проведено в 1С, позначте його внесеним. "
                "Резерв перестане зменшувати залишок лише після наступного успішного "
                "імпорту цього товару з 1С."
            ),
            "fields": ("entered_in_1c_at", "cancelled_at", "display_products", "display_reservations"),
        }),
    )

    @admin.action(description="Відмітити внесеним в 1С")
    def mark_entered_in_1c(self, request, queryset):
        for order in queryset:
            mark_entered_in_1c(order, request.user.get_username())
        self.message_user(request, "Замовлення позначено внесеними в 1С. Резерв зніметься після наступного імпорту цих товарів.")

    @admin.action(description="Скасувати замовлення і звільнити резерв")
    def cancel_and_release(self, request, queryset):
        for order in queryset:
            cancel_order(order, request.user.get_username())
        self.message_user(request, "Замовлення скасовано, резерв звільнено.")

    @admin.action(description="Повторно надіслати лист")
    def resend_order_email(self, request, queryset):
        if request.POST.get("confirm_resend") != "yes":
            return render(request, "admin/carts/resend_confirmation.html", {
                **self.admin_site.each_context(request),
                "orders": queryset,
                "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
            })
        for order in queryset:
            send_order_notifications(order.id, "confirmation", force=True)
        self.message_user(request, "Листи надіслано повторно.")

    def display_products(self, obj):
        products = obj.products
        if not products:
            return "Немає товарів."

        html = '<table style="width:100%; border:1px solid black; border-collapse:collapse;">'
        html += "<thead><tr><th>Назва</th><th>Зі складу</th><th>Передзамовлення</th><th>Ціна</th><th>Артикул</th></tr></thead><tbody>"
        for product in products:
            html += (
                "<tr>"
                f"<td>{escape(product.get('name', ''))}</td>"
                f"<td>{escape(product.get('quantity', 0))}</td>"
                f"<td>{escape(product.get('preorder', 0))}</td>"
                f"<td>{escape(product.get('price', product.get('unit_price', 0)))} грн</td>"
                f"<td>{escape(product.get('model', ''))}</td>"
                "</tr>"
            )
        html += "</tbody></table>"
        return mark_safe(html)
    display_products.short_description = "Склад і передзамовлення"

    def display_reservations(self, obj):
        reservations = obj.reservations.all()
        if not reservations:
            return "Немає резерву."
        html = "<ul>"
        for reservation in reservations:
            html += (
                f"<li>{escape(reservation.product)} — {reservation.quantity}, "
                f"{escape(reservation.get_status_display())}</li>"
            )
        html += "</ul>"
        return mark_safe(html)
    display_reservations.short_description = "Резерв"

    def save_model(self, request, obj, form, change):
        old_status = None
        if change and obj.pk:
            old_status = Order.objects.filter(pk=obj.pk).values_list("status", flat=True).first()
        requested_status = obj.status
        lifecycle_transition = (
            change
            and old_status != requested_status
            and requested_status
            in {Order.STATUS_ENTERED_IN_1C, Order.STATUS_CANCELLED}
        )
        if lifecycle_transition:
            # Save other edited fields first, but route lifecycle statuses
            # through the same functions as admin actions.
            obj.status = old_status
        if not obj.user and request.user.is_authenticated:
            obj.user = request.user
        super().save_model(request, obj, form, change)
        if lifecycle_transition:
            if requested_status == Order.STATUS_ENTERED_IN_1C:
                mark_entered_in_1c(obj, request.user.get_username())
            else:
                cancel_order(obj, request.user.get_username())
            obj.refresh_from_db()
            return
        if change and old_status is not None and old_status != obj.status:
            OrderStatusLog.objects.create(
                order=obj,
                old_status=old_status,
                new_status=obj.status,
                actor=request.user.get_username(),
                comment="admin edit",
            )


@admin.register(PreOrder)
class PreOrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'name', 'created_at', 'display_products')
    search_fields = ('order_number', 'name', 'user__username')
    readonly_fields = ('display_products',)
    exclude = ('products',)

    def display_products(self, obj):
        products = obj.products
        if isinstance(products, str):  # Проверяем, если products – строка
            products = json.loads(products)  # Преобразуем JSON-строку в словарь

        if not products:
            return "No products ordered."

            # Создаем HTML-таблицу
        html = '<table style="width:100%; border:1px solid black; border-collapse:collapse;">'
        html += '<thead><tr><th>Назва продукту</th><th>К-сть</th><th>Ціна</th><th>Артикул</th></tr></thead>'
        html += '<tbody>'

        for product in products:
            product_name = product.get("name", "N/A")
            quantity = product.get("quantity", 0)
            price = product.get("price", 0)
            model = product.get("model", "")
            html += f'<tr><td>{product_name}</td><td>{quantity}</td><td>{price} грн</td><td>{model}</td></tr>'

        html += '</tbody></table>'
        return mark_safe(html)

    def save_model(self, request, obj, form, change):
        # Устанавливаем пользователя, если он авторизован и еще не установлен
        if not obj.user and request.user.is_authenticated:
            obj.user = request.user
        super().save_model(request, obj, form, change)