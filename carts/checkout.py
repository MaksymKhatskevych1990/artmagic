import hashlib
import json
import logging
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from carts.models import (
    Order,
    OrderNotificationDelivery,
    OrderStatusLog,
    PreOrder,
    StockReservation,
)
from carts.stock import (
    StockError,
    checkout_enabled,
    money_str,
    parse_cart_items,
    quote_cart,
    reservation_minutes,
)
from products.models import Products
from carts.utils import create_order, get_delivery_info, prepare_email_context, send_email
from liqpay_app.models import Payment

logger = logging.getLogger("carts.checkout")

PAYMENT_LABELS = {
    "liqpay": "Онлайн-оплата банківською карткою",
    "payment_card": "Оплата за реквізитами",
    "payment_real": "Оплата у точці видачі",
}
DELIVERY_LABELS = {
    "artmagic_department": "Самовивіз",
    "new_post_department": "Відділення Нової пошти",
    "new_post_packing": "Поштомат Нової пошти",
    "new_post_address": "Кур'єрська доставка Нової пошти",
    "ukr_post": "Укрпошта",
}
LIQPAY_FAILURE = {"failure", "error", "reversed"}
CALLBACK_FIELDS = ("status", "amount", "currency", "order_id", "payment_id", "err_code", "err_description")


class CheckoutError(Exception):
    def __init__(self, http_status, payload):
        self.http_status = http_status
        self.payload = payload
        super().__init__(payload.get("message", "checkout error"))


def perform_checkout(data, request):
    normalized = normalize_checkout_data(data)
    if (
        normalized.get("selectedPayment") == "liqpay"
        and normalized.get("orderNumber")
        and not normalized.get("client_request_id")
    ):
        existing = Order.objects.filter(
            order_number=normalized["orderNumber"],
            payment_code="liqpay",
        ).first()
        if existing:
            return order_payload(existing, request)
    # Compatibility for a page opened before the new JavaScript was deployed.
    # New clients always send their own UUID. Reuse a short-lived server-side
    # key for old clients so a double click cannot create two manual orders.
    if not normalized.get("client_request_id"):
        normalized["client_request_id"] = legacy_request_id(
            normalized,
            request,
        )
    if not checkout_enabled():
        return legacy_checkout(normalized, request)

    request_id = parse_request_id(normalized.get("client_request_id"))
    existing = Order.objects.filter(client_request_id=request_id).first()
    if existing:
        logger.info(
            "checkout_idempotent client_request_id=%s order=%s",
            request_id,
            existing.order_number,
        )
        return order_payload(existing, request)

    validate_contacts(normalized)
    try:
        delivery_method, address = get_delivery_info(normalized)
    except Exception as exc:
        logger.info("checkout_delivery_failed client_request_id=%s", request_id)
        raise CheckoutError(400, {"status": "error", "message": "Перевірте дані доставки"}) from exc
    if not delivery_method:
        raise CheckoutError(400, {"status": "error", "message": "Оберіть спосіб доставки"})

    raw_items = normalized.get("products") or normalized.get("items") or []
    try:
        parse_cart_items(raw_items)
    except StockError as exc:
        raise CheckoutError(400, {"status": "error", "message": exc.message}) from exc
    try:
        with transaction.atomic():
            existing = Order.objects.select_for_update().filter(client_request_id=request_id).first()
            if existing:
                order_id = existing.id
            else:
                order_id = create_checked_order(
                    normalized,
                    request,
                    request_id,
                    raw_items,
                    delivery_method,
                    address,
                )
    except IntegrityError:
        existing = Order.objects.filter(client_request_id=request_id).first()
        if existing is None:
            raise
        logger.info(
            "checkout_idempotent_race client_request_id=%s order=%s",
            request_id,
            existing.order_number,
        )
        return order_payload(existing, request)

    return order_payload(Order.objects.get(pk=order_id), request)


def create_checked_order(data, request, request_id, raw_items, delivery_method, address):
    parsed_items = parse_cart_items(raw_items)
    locked_ids = sorted({item["id"] for item in parsed_items})
    list(Products.objects.select_for_update().filter(id__in=locked_ids).order_by("id"))
    # A concurrent retry may have committed while this request was waiting for
    # the product lock. Return it instead of recalculating stock and producing
    # a false 409 response.
    existing = Order.objects.filter(client_request_id=request_id).first()
    if existing:
        return existing.id
    try:
        quote = quote_cart(raw_items)
    except StockError as exc:
        raise CheckoutError(400, {"status": "error", "message": exc.message}) from exc

    lines = quote["_lines"]
    if any(line["unavailable"] for line in lines):
        raise CheckoutError(400, {
            "status": "error",
            "message": "Деякі товари недоступні. Оновіть кошик.",
            "cart": public_from_quote(quote),
        })

    confirmed = data.get("confirmed_fingerprint")
    if not confirmed or confirmed != quote["fingerprint"]:
        logger.info(
            "checkout_stock_changed client_request_id=%s payment=%s",
            request_id,
            data.get("selectedPayment"),
        )
        raise CheckoutError(409, {
            "status": "stock_changed",
            "message": "Наявність або ціна змінились. Підтвердіть кошик ще раз.",
            "cart": public_from_quote(quote),
        })

    payment_code = data.get("selectedPayment")
    is_liqpay = payment_code == "liqpay"
    now = timezone.now()
    user = request.user if getattr(request.user, "is_authenticated", False) else None
    snapshot = [snapshot_line(line) for line in lines]
    order = Order(
        user=user,
        name=data.get("name", "").strip(),
        phone=str(data.get("phone", "")).strip(),
        email=str(data.get("email", "")).strip(),
        payment=PAYMENT_LABELS.get(payment_code, ""),
        address=address,
        total_price=money_str(Decimal_sum(lines)),
        products=snapshot,
        status=Order.STATUS_PENDING_PAYMENT if is_liqpay else Order.STATUS_NEW,
        payment_code=payment_code,
        delivery_code=data.get("selectedDelivery") or "",
        client_request_id=request_id,
        stock_checked_at=now,
    )
    order.save()
    OrderStatusLog.objects.create(
        order=order,
        old_status="",
        new_status=order.status,
        actor="checkout",
        comment=payment_code,
    )

    preorder_lines = [line for line in snapshot if line["preorder"]]
    if preorder_lines:
        PreOrder.objects.create(
            user=user,
            order=order,
            name=order.name,
            products=preorder_lines,
            quantity=sum(line["preorder"] for line in preorder_lines),
        )

    expires_at = now + timedelta(minutes=reservation_minutes()) if is_liqpay else None
    reservation_status = (
        StockReservation.STATUS_PENDING_PAYMENT if is_liqpay else StockReservation.STATUS_ACTIVE
    )
    for line in lines:
        if not line["reserved_quantity"]:
            continue
        StockReservation.objects.create(
            order=order,
            product_id=line["id"],
            quantity=line["reserved_quantity"],
            status=reservation_status,
            expires_at=expires_at,
        )
        logger.info(
            "reservation_created order=%s product=%s quantity=%s status=%s",
            order.order_number,
            line["id"],
            line["reserved_quantity"],
            reservation_status,
        )

    if is_liqpay:
        build_liqpay_payment(order, data.get("selectedDelivery"))
    else:
        queue_order_notifications(
            order,
            OrderNotificationDelivery.KIND_CONFIRMATION,
        )
    logger.info(
        "checkout_created client_request_id=%s order=%s payment=%s total=%s",
        request_id,
        order.order_number,
        payment_code,
        order.total_price,
    )
    return order.id


def legacy_checkout(data, request):
    request_id = None
    if data.get("client_request_id"):
        request_id = parse_request_id(data.get("client_request_id"))
        existing = Order.objects.filter(client_request_id=request_id).first()
        if existing:
            return order_payload(existing, request)
    validate_contacts(data)
    delivery_method, address = get_delivery_info(data)
    user = request.user if getattr(request.user, "is_authenticated", False) else None
    quote = quote_cart(data.get("products") or data.get("items") or [])
    if any(line["unavailable"] for line in quote["_lines"]):
        raise CheckoutError(
            400,
            {
                "status": "error",
                "message": "Деякі товари недоступні. Оновіть кошик.",
                "cart": public_from_quote(quote),
            },
        )
    data = dict(data)
    data["products"] = [snapshot_line(line) for line in quote["_lines"]]
    data["amount"] = money_str(Decimal_sum(quote["_lines"]))
    order = create_order(data, user, address)
    order.payment_code = data.get("selectedPayment") or ""
    order.delivery_code = data.get("selectedDelivery") or ""
    if request_id:
        order.client_request_id = request_id
    order.save()
    if data.get("selectedPayment") == "liqpay":
        order.status = Order.STATUS_PENDING_PAYMENT
        order.save(update_fields=["status", "updated_at"])
        build_liqpay_payment(order, data.get("selectedDelivery"))
        return order_payload(order, request)
    order.status = Order.STATUS_NEW
    order.save(update_fields=["status", "updated_at"])
    queue_order_notifications(
        order,
        OrderNotificationDelivery.KIND_CONFIRMATION,
    )
    return order_payload(order, request)


def order_payload(order, request):
    payload = {
        "status": "success",
        "orderNumber": order.order_number,
        "orderStatus": order.status,
        "payment": order.payment,
        "amount": money_str(order.total_price),
    }
    if order.payment_code == "liqpay" and order.status == Order.STATUS_PENDING_PAYMENT:
        payload["formHtml"] = render_liqpay_form(order, request)
    elif order.payment_code == "liqpay" and order.status == Order.STATUS_PAID:
        payload["alreadyPaid"] = True
    return payload


def build_liqpay_payment(order, delivery_code):
    liqpay_order_id = f"{order.order_number}-{delivery_code}"
    Payment.objects.update_or_create(
        checkout_order=order,
        defaults={
            "user": order.user,
            "amount": order.total_price,
            "order_id": liqpay_order_id,
            "liqpay_order_id": liqpay_order_id,
            "status": "pending",
        },
    )


def render_liqpay_form(order, request):
    public_key = getattr(settings, "LIQPAY_PUBLIC_KEY", None)
    private_key = getattr(settings, "LIQPAY_PRIVATE_KEY", None)
    if not public_key or not private_key:
        raise CheckoutError(500, {"status": "error", "message": "Оплата карткою тимчасово недоступна"})
    from liqpay.liqpay3 import LiqPay

    liqpay = LiqPay(public_key, private_key)
    params = {
        "public_key": public_key,
        "action": "pay",
        "amount": money_str(order.total_price),
        "currency": "UAH",
        "description": f"ArtMagic замовлення {order.order_number}",
        "order_id": f"{order.order_number}-{order.delivery_code}",
        "version": "3",
        "server_url": request.build_absolute_uri("/payment/liqpay-callback/"),
        "result_url": request.build_absolute_uri("/"),
    }
    form_html = liqpay.cnb_form(params)
    return form_html.replace("<form", '<form target="_blank"', 1)


def handle_liqpay_callback(decoded):
    raw_order_id = str(decoded.get("order_id") or "")
    callback_status = decoded.get("status")
    summary = {key: decoded.get(key) for key in CALLBACK_FIELDS if key in decoded}
    logger.info(
        "liqpay_callback liqpay_order_id=%s status=%s signature=ok",
        raw_order_id,
        callback_status,
    )

    try:
        with transaction.atomic():
            payment = (
                Payment.objects.select_for_update()
                .filter(
                    Q(liqpay_order_id=raw_order_id) | Q(order_id=raw_order_id)
                )
                .first()
            )
            if payment is None or payment.checkout_order is None:
                logger.warning(
                    "liqpay_callback payment_not_found liqpay_order_id=%s",
                    raw_order_id,
                )
                return "missing"
            order = Order.objects.select_for_update().get(
                pk=payment.checkout_order_id
            )
            if order.payment_code != "liqpay":
                logger.error(
                    "liqpay_callback non_liqpay_order order=%s",
                    order.order_number,
                )
                return "mismatch"

            try:
                callback_amount = Decimal(str(decoded.get("amount"))).quantize(
                    Decimal("0.01")
                )
            except (InvalidOperation, TypeError, ValueError):
                callback_amount = None
            if (
                callback_amount != payment.amount
                or decoded.get("currency") != "UAH"
                or raw_order_id
                not in {payment.order_id, payment.liqpay_order_id}
            ):
                logger.error(
                    "liqpay_callback mismatch order=%s amount_ok=%s currency=%s",
                    order.order_number,
                    callback_amount == payment.amount,
                    decoded.get("currency"),
                )
                return "mismatch"

            payment.callback_summary = summary
            payment.last_callback_at = timezone.now()

            if callback_status == "success":
                if order.status in {
                    Order.STATUS_PAID,
                    Order.STATUS_PAID_STOCK_CONFLICT,
                }:
                    # Keep the terminal successful payment status. A repeated
                    # callback can safely retry only missing email deliveries.
                    payment.status = "success"
                    payment.save(
                        update_fields=[
                            "status",
                            "callback_summary",
                            "last_callback_at",
                            "updated_at",
                        ]
                    )
                    queue_order_notifications(
                        order,
                        OrderNotificationDelivery.KIND_CONFIRMATION,
                    )
                    return "duplicate"
                previous_status = order.status
                stock_restored = activate_paid_reservations(order)
                order.paid_at = timezone.now()
                order.status = (
                    Order.STATUS_PAID
                    if stock_restored
                    else Order.STATUS_PAID_STOCK_CONFLICT
                )
                order.save(
                    update_fields=["paid_at", "status", "updated_at"]
                )
                OrderStatusLog.objects.create(
                    order=order,
                    old_status=previous_status,
                    new_status=order.status,
                    actor="liqpay",
                    comment=(
                        "payment success"
                        if stock_restored
                        else "payment success; stock reservation conflict"
                    ),
                )
                payment.status = "success"
                payment.save(
                    update_fields=[
                        "status",
                        "callback_summary",
                        "last_callback_at",
                        "updated_at",
                    ]
                )
                queue_order_notifications(
                    order,
                    OrderNotificationDelivery.KIND_CONFIRMATION,
                )
                return "paid" if stock_restored else "paid_stock_conflict"

            if callback_status in LIQPAY_FAILURE:
                if order.status in {
                    Order.STATUS_PAID,
                    Order.STATUS_PAID_STOCK_CONFLICT,
                    Order.STATUS_ENTERED_IN_1C,
                    Order.STATUS_COMPLETED,
                }:
                    # Never let an out-of-order failure corrupt a successful
                    # terminal payment record.
                    payment.save(
                        update_fields=[
                            "callback_summary",
                            "last_callback_at",
                            "updated_at",
                        ]
                    )
                    return "ignored"
                payment.status = str(callback_status)[:20]
                payment.save(
                    update_fields=[
                        "status",
                        "callback_summary",
                        "last_callback_at",
                        "updated_at",
                    ]
                )
                release_reservations(order, StockReservation.STATUS_RELEASED)
                if order.status != Order.STATUS_PAYMENT_FAILED:
                    order.set_status(Order.STATUS_PAYMENT_FAILED, actor="liqpay", comment=str(callback_status))
                return "failed"
            payment.status = str(callback_status or "")[:20]
            payment.save(
                update_fields=[
                    "status",
                    "callback_summary",
                    "last_callback_at",
                    "updated_at",
                ]
            )
            return "pending"
    except IntegrityError:
        logger.warning(
            "liqpay_callback duplicate_payment liqpay_order_id=%s",
            raw_order_id,
        )
        return "duplicate"


def activate_paid_reservations(order):
    reservations = list(order.reservations.select_for_update().order_by("product_id"))
    if not reservations:
        return True
    product_ids = sorted({reservation.product_id for reservation in reservations})
    products = {
        product.id: product
        for product in Products.objects.select_for_update()
        .filter(id__in=product_ids)
        .order_by("id")
    }
    needs_restore = [
        reservation
        for reservation in reservations
        if reservation.status
        in {
            StockReservation.STATUS_RELEASED,
            StockReservation.STATUS_EXPIRED,
        }
    ]
    for reservation in needs_restore:
        product = products.get(reservation.product_id)
        if product is None:
            return False
        held_by_others = (
            StockReservation.objects.filter(
                product_id=reservation.product_id,
                status__in=StockReservation.HOLDING_STATUSES,
            )
            .exclude(order=order)
            .aggregate(total=Sum("quantity"))["total"]
            or 0
        )
        available = max(int(product.quantity or 0) - int(held_by_others), 0)
        if available < reservation.quantity:
            return False
    now = timezone.now()
    order.reservations.filter(
        status__in=[
            StockReservation.STATUS_PENDING_PAYMENT,
            StockReservation.STATUS_RELEASED,
            StockReservation.STATUS_EXPIRED,
        ]
    ).update(
        status=StockReservation.STATUS_ACTIVE,
        expires_at=None,
        released_at=None,
        updated_at=now,
    )
    return True


def expire_pending_reservations():
    now = timezone.now()
    cutoff = now - timedelta(minutes=reservation_minutes())
    order_ids = list(
        Order.objects.filter(status=Order.STATUS_PENDING_PAYMENT)
        .filter(
            Q(created_at__lte=cutoff)
            | Q(
                reservations__status=StockReservation.STATUS_PENDING_PAYMENT,
                reservations__expires_at__isnull=False,
                reservations__expires_at__lte=now,
            )
        )
        .values_list("id", flat=True)
        .distinct()
    )
    expired_orders = 0
    for order_id in order_ids:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=order_id)
            if order.status != Order.STATUS_PENDING_PAYMENT:
                continue
            reservations = order.reservations.select_for_update().filter(
                status=StockReservation.STATUS_PENDING_PAYMENT,
            )
            reservation_count = reservations.update(
                status=StockReservation.STATUS_EXPIRED,
                released_at=now,
                updated_at=now,
            )
            order.set_status(
                Order.STATUS_EXPIRED,
                actor="system",
                comment="payment timeout",
            )
            Payment.objects.filter(checkout_order=order).exclude(
                status="success"
            ).update(status="expired")
            expired_orders += 1
            logger.info(
                "reservations_expired order=%s count=%s",
                order.order_number,
                reservation_count,
            )
    return expired_orders


def mark_entered_in_1c(order, actor):
    if order.status not in {
        Order.STATUS_NEW,
        Order.STATUS_PAID,
        Order.STATUS_PROCESSING,
    }:
        return order
    now = timezone.now()
    order.entered_in_1c_at = now
    order.save(update_fields=["entered_in_1c_at", "updated_at"])
    order.reservations.filter(
        status__in=[StockReservation.STATUS_ACTIVE, StockReservation.STATUS_PENDING_PAYMENT]
    ).update(status=StockReservation.STATUS_PENDING_1C, updated_at=now)
    order.set_status(Order.STATUS_ENTERED_IN_1C, actor=actor, comment="entered in 1C")
    logger.info("order_entered_in_1c order=%s actor=%s", order.order_number, actor)
    return order


def cancel_order(order, actor):
    now = timezone.now()
    order.cancelled_at = now
    order.save(update_fields=["cancelled_at", "updated_at"])
    release_reservations(order, StockReservation.STATUS_RELEASED)
    order.set_status(Order.STATUS_CANCELLED, actor=actor, comment="cancelled")
    logger.info("order_cancelled order=%s actor=%s", order.order_number, actor)
    return order


def release_reservations(order, status):
    now = timezone.now()
    order.reservations.exclude(
        status__in=[
            StockReservation.STATUS_RECONCILED,
            StockReservation.STATUS_RELEASED,
            StockReservation.STATUS_EXPIRED,
        ]
    ).update(status=status, released_at=now, updated_at=now)


def queue_order_notifications(order, kind, force=False):
    recipients = []
    if settings.EMAIL_HOST_USER:
        recipients.append(
            (
                OrderNotificationDelivery.RECIPIENT_SHOP,
                settings.EMAIL_HOST_USER,
            )
        )
    if order.email:
        recipients.append(
            (OrderNotificationDelivery.RECIPIENT_CUSTOMER, order.email)
        )
    for recipient_type, recipient in recipients:
        delivery, _ = OrderNotificationDelivery.objects.get_or_create(
            order=order,
            kind=kind,
            recipient_type=recipient_type,
            defaults={"recipient": recipient},
        )
        updates = []
        if delivery.recipient != recipient:
            delivery.recipient = recipient
            updates.append("recipient")
        if force:
            delivery.status = OrderNotificationDelivery.STATUS_PENDING
            delivery.sent_at = None
            delivery.last_error = ""
            updates.extend(["status", "sent_at", "last_error"])
        if updates:
            delivery.save(update_fields=[*set(updates), "updated_at"])
    transaction.on_commit(
        lambda order_id=order.id, notification_kind=kind: send_pending_notifications(
            order_id, notification_kind
        )
    )


def send_pending_notifications(order_id, kind):
    order = Order.objects.filter(pk=order_id).first()
    if order is None:
        return
    stale_claim = timezone.now() - timedelta(minutes=10)
    delivery_ids = list(
        order.notification_deliveries.filter(kind=kind)
        .exclude(status=OrderNotificationDelivery.STATUS_SENT)
        .filter(
            Q(
                status__in=[
                    OrderNotificationDelivery.STATUS_PENDING,
                    OrderNotificationDelivery.STATUS_FAILED,
                ]
            )
            | Q(
                status=OrderNotificationDelivery.STATUS_SENDING,
                updated_at__lte=stale_claim,
            )
        )
        .values_list("id", flat=True)
    )
    context = email_context(
        order,
        awaiting=kind == OrderNotificationDelivery.KIND_AWAITING_PAYMENT,
    )
    for delivery_id in delivery_ids:
        with transaction.atomic():
            delivery = (
                OrderNotificationDelivery.objects.select_for_update()
                .filter(pk=delivery_id)
                .first()
            )
            if delivery is None or delivery.status == delivery.STATUS_SENT:
                continue
            if (
                delivery.status == delivery.STATUS_SENDING
                and delivery.updated_at > stale_claim
            ):
                continue
            delivery.status = delivery.STATUS_SENDING
            delivery.attempts += 1
            delivery.save(update_fields=["status", "attempts", "updated_at"])

        if delivery.recipient_type == delivery.RECIPIENT_SHOP:
            subject = f"Замовлення №: {order.order_number}"
            template = "carts/email_template.html"
        else:
            subject = (
                "Очікуємо оплату замовлення"
                if kind == delivery.KIND_AWAITING_PAYMENT
                else "Ваше замовлення прийняте"
            )
            template = "users/email_template_user.html"
        try:
            send_email(delivery.recipient, context, subject, template)
        except Exception as exc:
            OrderNotificationDelivery.objects.filter(pk=delivery.id).update(
                status=OrderNotificationDelivery.STATUS_FAILED,
                last_error=str(exc)[:1000],
                updated_at=timezone.now(),
            )
            logger.exception(
                "order_email_failed order=%s kind=%s recipient_type=%s",
                order.order_number,
                kind,
                delivery.recipient_type,
            )
            continue
        OrderNotificationDelivery.objects.filter(pk=delivery.id).update(
            status=OrderNotificationDelivery.STATUS_SENT,
            sent_at=timezone.now(),
            last_error="",
            updated_at=timezone.now(),
        )
        logger.info(
            "order_email_sent order=%s kind=%s recipient_type=%s",
            order.order_number,
            kind,
            delivery.recipient_type,
        )

    expected = order.notification_deliveries.filter(kind=kind)
    if expected.exists() and not expected.exclude(
        status=OrderNotificationDelivery.STATUS_SENT
    ).exists():
        timestamp_field = (
            "awaiting_notice_sent_at"
            if kind == OrderNotificationDelivery.KIND_AWAITING_PAYMENT
            else "notifications_sent_at"
        )
        Order.objects.filter(pk=order.id).update(
            **{timestamp_field: timezone.now()}
        )


def send_order_notifications(order_id, kind, force=False):
    """Backward-compatible admin entry point."""
    order = Order.objects.filter(pk=order_id).first()
    if order is None:
        return
    normalized_kind = {
        "awaiting": OrderNotificationDelivery.KIND_AWAITING_PAYMENT,
        "confirmation": OrderNotificationDelivery.KIND_CONFIRMATION,
    }.get(kind, kind)
    queue_order_notifications(order, normalized_kind, force=force)


def retry_pending_notifications():
    stale_claim = timezone.now() - timedelta(minutes=10)
    pending = (
        OrderNotificationDelivery.objects.exclude(
            status=OrderNotificationDelivery.STATUS_SENT
        )
        .filter(
            Q(
                status__in=[
                    OrderNotificationDelivery.STATUS_PENDING,
                    OrderNotificationDelivery.STATUS_FAILED,
                ]
            )
            | Q(
                status=OrderNotificationDelivery.STATUS_SENDING,
                updated_at__lte=stale_claim,
            )
        )
        .values_list("order_id", "kind")
        .distinct()
    )
    attempted = 0
    for order_id, kind in pending:
        send_pending_notifications(order_id, kind)
        attempted += 1
    return attempted


def email_context(order, awaiting=False):
    products = []
    preorders = []
    stock_total = 0
    preorder_total = 0
    for item in order.products or []:
        price = item.get("unit_price", item.get("price", "0.00"))
        row = dict(item)
        row["price"] = price
        quantity = int(item.get("quantity") or 0)
        preorder = int(item.get("preorder") or 0)
        unit = item.get("unit_price") or item.get("price") or "0"
        from decimal import Decimal
        if quantity:
            products.append(row)
            stock_total += Decimal(str(unit)) * quantity
        if preorder:
            preorders.append(row)
            preorder_total += Decimal(str(unit)) * preorder
    return {
        "name": order.name,
        "phone": order.phone,
        "email": order.email,
        "payment": order.payment,
        "payment_status": payment_status_label(order),
        "awaiting_payment": awaiting,
        "address": order.address,
        "products": products,
        "preorder_product": preorders,
        "preorder_total_price": money_str(preorder_total),
        "stock_total": money_str(stock_total),
        "total_price": money_str(order.total_price),
        "delivery_method": DELIVERY_LABELS.get(order.delivery_code, ""),
        "order_number": order.order_number,
    }


def payment_status_label(order):
    if order.status == Order.STATUS_PAID:
        return "Оплачено"
    if order.status == Order.STATUS_PAID_STOCK_CONFLICT:
        return "Оплачено, менеджер перевіряє наявність"
    if order.status == Order.STATUS_PENDING_PAYMENT:
        return "Очікує оплати"
    if order.status == Order.STATUS_PAYMENT_FAILED:
        return "Оплату відхилено"
    if order.status == Order.STATUS_EXPIRED:
        return "Час на оплату минув"
    if order.payment_code == "payment_real":
        return "Оплата при отриманні"
    if order.payment_code == "payment_card":
        return "Оплата за реквізитами"
    return order.payment or ""


def normalize_checkout_data(data):
    if not isinstance(data, dict):
        raise CheckoutError(400, {"status": "error", "message": "Некоректні дані замовлення"})
    if isinstance(data.get("fullName"), dict):
        return {
            "name": _field_value(data.get("fullName")),
            "phone": _field_value(data.get("clientPhone")),
            "email": _field_value(data.get("email")),
            "city": _field_value(data.get("city")),
            "address": _field_value(data.get("address")),
            "area": _field_value(data.get("area")),
            "department": _field_value(data.get("department")),
            "products": data.get("products") or data.get("items") or [],
            "selectedDelivery": data.get("selectedDelivery") or "",
            "selectedPayment": data.get("selectedPayment") or "",
            "amount": data.get("amount"),
            "client_request_id": data.get("client_request_id"),
            "confirmed_fingerprint": data.get("confirmed_fingerprint"),
            "orderNumber": data.get("orderNumber"),
        }
    return data


def _field_value(value):
    if isinstance(value, dict):
        return value.get("value", "")
    return value or ""


def legacy_request_id(data, request):
    raw_items = data.get("products") or data.get("items") or []
    cart = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        cart.append({
            "id": item.get("id"),
            "requested_quantity": item.get("requested_quantity"),
            "quantity": item.get("quantity"),
            "preorder": item.get("preorder"),
        })
    signature_payload = {
        "name": data.get("name"),
        "phone": data.get("phone"),
        "email": data.get("email"),
        "delivery": data.get("selectedDelivery"),
        "payment": data.get("selectedPayment"),
        "cart": sorted(cart, key=lambda item: str(item["id"])),
    }
    signature = hashlib.sha256(
        json.dumps(
            signature_payload,
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    session = getattr(request, "session", None)
    now_timestamp = int(timezone.now().timestamp())
    if session is not None:
        previous = session.get("legacy_checkout_idempotency") or {}
        if (
            previous.get("signature") == signature
            and now_timestamp - int(previous.get("created_at") or 0) < 300
        ):
            return previous["request_id"]
    request_id = str(uuid.uuid4())
    if session is not None:
        session["legacy_checkout_idempotency"] = {
            "signature": signature,
            "request_id": request_id,
            "created_at": now_timestamp,
        }
    return request_id


def validate_contacts(data):
    if not str(data.get("name") or "").strip():
        raise CheckoutError(400, {"status": "error", "message": "Вкажіть ім'я"})
    if not str(data.get("phone") or "").strip():
        raise CheckoutError(400, {"status": "error", "message": "Вкажіть телефон"})
    email = str(data.get("email") or "").strip()
    if "@" not in email:
        raise CheckoutError(400, {"status": "error", "message": "Вкажіть email"})
    if data.get("selectedPayment") not in PAYMENT_LABELS:
        raise CheckoutError(400, {"status": "error", "message": "Оберіть спосіб оплати"})
    if data.get("selectedDelivery") not in DELIVERY_LABELS:
        raise CheckoutError(400, {"status": "error", "message": "Оберіть спосіб доставки"})


def parse_request_id(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise CheckoutError(400, {"status": "error", "message": "Потрібен ключ оформлення замовлення"}) from exc


def snapshot_line(line):
    unit = line["unit_price"]
    from decimal import Decimal
    line_total = Decimal(unit) * (line["quantity"] + line["preorder"])
    return {
        "id": line["id"],
        "model": line["model"],
        "name": line["name"],
        "unit_price": unit,
        "price": unit,
        "requested_quantity": line["requested_quantity"],
        "quantity": line["quantity"],
        "preorder": line["preorder"],
        "line_total": money_str(line_total),
        "stock_quantity_at_checkout": line["stock_quantity_at_checkout"],
        "reserved_quantity": line["reserved_quantity"],
    }


def Decimal_sum(lines):
    from decimal import Decimal
    total = Decimal("0.00")
    for line in lines:
        total += Decimal(line["unit_price"]) * (line["quantity"] + line["preorder"])
    return total


def public_from_quote(quote):
    payload = dict(quote)
    payload.pop("_lines", None)
    return payload
