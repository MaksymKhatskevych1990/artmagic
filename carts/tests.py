import base64
import hashlib
import json
import threading
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.db import connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from carts.checkout import (
    CheckoutError,
    mark_entered_in_1c,
    perform_checkout,
    send_order_notifications,
)
from carts.models import (
    Order,
    OrderNotificationDelivery,
    StockReservation,
)
from carts.stock import reconcile_pending_reservations
from liqpay_app.models import Payment
from products.models import Products, SyncRun
from products.sync import is_sync_stale

TEST_SETTINGS = dict(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    LIQPAY_PUBLIC_KEY="sandbox_public",
    LIQPAY_PRIVATE_KEY="sandbox_private",
    ONEC_API_KEY="test-onec-key",
    ORDER_CHECKOUT_V2=True,
    SYNC_STALE_HOURS=26,
    EMAIL_HOST_USER="shop@example.com",
)


def post_json(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


@override_settings(**TEST_SETTINGS)
class CartRefreshTests(TestCase):
    def setUp(self):
        self.product = Products.objects.create(
            name="Фольга золото",
            model="521000000",
            price=Decimal("190.00"),
            quantity=5,
            status=True,
        )

    def test_added_at_five_then_stock_becomes_zero(self):
        self.product.quantity = 0
        self.product.save(update_fields=["quantity"])
        response = post_json(self.client, "/cart/refresh/", {
            "items": [{"id": self.product.id, "quantity": 2, "preorder": 0, "price": "190.00"}],
        })
        self.assertEqual(response.status_code, 200)
        item = response.json()["items"][0]
        self.assertTrue(response.json()["changed"])
        self.assertEqual(item["quantity"], 0)
        self.assertEqual(item["preorder"], 2)
        self.assertEqual(item["available"], 0)
        self.assertTrue(item["stock_changed"])

    def test_missing_and_disabled_products_are_reported(self):
        self.product.status = False
        self.product.save(update_fields=["status"])
        response = post_json(self.client, "/cart/refresh/", {
            "items": [
                {"id": self.product.id, "requested_quantity": 1},
                {"id": 999999, "requested_quantity": 1},
            ],
        })
        self.assertEqual(response.status_code, 200)
        reasons = {item["id"]: item["reason"] for item in response.json()["items"]}
        self.assertEqual(reasons[self.product.id], "disabled")
        self.assertEqual(reasons[999999], "not_found")
        self.assertTrue(all(item["unavailable"] for item in response.json()["items"]))

    def test_price_change_is_flagged_and_server_price_is_used(self):
        response = post_json(self.client, "/cart/refresh/", {
            "items": [{"id": self.product.id, "requested_quantity": 1, "price": "1.00"}],
        })
        item = response.json()["items"][0]
        self.assertTrue(item["price_changed"])
        self.assertEqual(item["unit_price"], "190.00")

    def test_duplicate_lines_are_merged(self):
        response = post_json(self.client, "/cart/refresh/", {
            "items": [
                {"id": self.product.id, "requested_quantity": 1},
                {"id": self.product.id, "requested_quantity": 2},
            ],
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 1)
        self.assertEqual(response.json()["items"][0]["requested_quantity"], 3)
        self.assertEqual(response.json()["items"][0]["quantity"], 3)

    def test_invalid_payload_does_not_reserve_or_order(self):
        response = self.client.post("/cart/refresh/", data="{", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(StockReservation.objects.count(), 0)

    def test_old_quantity_plus_preorder_format(self):
        self.product.quantity = 1
        self.product.save(update_fields=["quantity"])
        response = post_json(self.client, "/cart/refresh/", {
            "items": [{"id": self.product.id, "quantity": 2, "preorder": 3, "price": "190.00"}],
        })
        item = response.json()["items"][0]
        self.assertEqual(item["requested_quantity"], 5)
        self.assertEqual(item["quantity"], 1)
        self.assertEqual(item["preorder"], 4)
        self.assertTrue(item["stock_changed"])

    def test_rejects_fractional_negative_and_too_many_lines(self):
        fractional = post_json(self.client, "/cart/refresh/", {
            "items": [{"id": self.product.id, "requested_quantity": 1.5}],
        })
        negative = post_json(self.client, "/cart/refresh/", {
            "items": [{"id": self.product.id, "requested_quantity": -1}],
        })
        too_many = post_json(self.client, "/cart/refresh/", {
            "items": [{"id": index, "requested_quantity": 1} for index in range(1, 52)],
        })
        self.assertEqual(fractional.status_code, 400)
        self.assertEqual(negative.status_code, 400)
        self.assertEqual(too_many.status_code, 400)


@override_settings(**TEST_SETTINGS)
class CheckoutTests(TestCase):
    def setUp(self):
        self.product = Products.objects.create(
            name="Фольга срібло",
            model="52200000",
            price=Decimal("190.00"),
            quantity=5,
            status=True,
        )

    def quote(self, quantity=1, preorder=0, price=None):
        response = post_json(self.client, "/cart/refresh/", {
            "items": [{
                "id": self.product.id,
                "quantity": quantity,
                "preorder": preorder,
                "price": "190.00" if price is None else price,
            }],
        })
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def checkout(self, quote, price="190.00", payment="payment_card", request_id=None):
        item = quote["items"][0]
        with self.captureOnCommitCallbacks(execute=True):
            return post_json(self.client, "/cart/checkout/", {
            "name": "Зеленіна Оксана",
            "phone": "0503964141",
            "email": "buyer@example.com",
            "selectedDelivery": "artmagic_department",
            "selectedPayment": payment,
            "products": [{
                "id": item["id"],
                "quantity": item["quantity"],
                "preorder": item["preorder"],
                "price": price,
            }],
            "client_request_id": request_id or str(uuid.uuid4()),
            "confirmed_fingerprint": quote["fingerprint"],
        })

    def test_sufficient_stock_reserves_server_price(self):
        response = self.checkout(self.quote(quantity=2), price="1.00")
        self.assertEqual(response.status_code, 200, response.content)
        order = Order.objects.get()
        self.assertEqual(order.total_price, Decimal("380.00"))
        self.assertEqual(order.products[0]["quantity"], 2)
        self.assertEqual(order.products[0]["unit_price"], "190.00")
        self.assertEqual(order.status, Order.STATUS_NEW)
        reservation = StockReservation.objects.get()
        self.assertEqual(reservation.quantity, 2)
        self.assertEqual(reservation.status, StockReservation.STATUS_ACTIVE)
        self.assertEqual(len(mail.outbox), 2)

    def test_partial_quantity_becomes_preorder(self):
        self.product.quantity = 2
        self.product.save(update_fields=["quantity"])
        response = self.checkout(self.quote(quantity=5))
        self.assertEqual(response.status_code, 200, response.content)
        line = Order.objects.get().products[0]
        self.assertEqual(line["quantity"], 2)
        self.assertEqual(line["preorder"], 3)
        self.assertEqual(StockReservation.objects.get().quantity, 2)
        self.assertEqual(Order.objects.get().preorders.get().order_id, Order.objects.get().id)

    def test_whole_line_becomes_preorder_without_reservation(self):
        self.product.quantity = 0
        self.product.save(update_fields=["quantity"])
        response = self.checkout(self.quote(quantity=2))
        self.assertEqual(response.status_code, 200, response.content)
        line = Order.objects.get().products[0]
        self.assertEqual(line["quantity"], 0)
        self.assertEqual(line["preorder"], 2)
        self.assertEqual(StockReservation.objects.count(), 0)

    def test_stale_confirmation_returns_conflict_and_creates_nothing(self):
        quote = self.quote(quantity=2)
        self.product.quantity = 0
        self.product.save(update_fields=["quantity"])
        response = self.checkout(quote)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["status"], "stock_changed")
        self.assertEqual(response.json()["cart"]["items"][0]["preorder"], 2)
        self.assertEqual(Order.objects.count(), 0)

    def test_same_request_id_returns_the_same_order(self):
        request_id = str(uuid.uuid4())
        quote = self.quote(quantity=1)
        first = self.checkout(quote, request_id=request_id)
        second = self.checkout(quote, request_id=request_id)
        self.assertEqual(first.json()["orderNumber"], second.json()["orderNumber"])
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 2)

    def test_failed_email_delivery_can_be_retried_without_duplicates(self):
        quote = self.quote(quantity=1)
        with patch(
            "carts.checkout.send_email",
            side_effect=[RuntimeError("smtp unavailable"), None],
        ):
            response = self.checkout(quote)
        self.assertEqual(response.status_code, 200, response.content)
        order = Order.objects.get()
        order.refresh_from_db()
        self.assertIsNone(order.notifications_sent_at)
        self.assertEqual(
            order.notification_deliveries.filter(
                status=OrderNotificationDelivery.STATUS_FAILED,
            ).count(),
            1,
        )
        self.assertEqual(
            order.notification_deliveries.filter(
                status=OrderNotificationDelivery.STATUS_SENT,
            ).count(),
            1,
        )

        with self.captureOnCommitCallbacks(execute=True):
            send_order_notifications(order.id, "confirmation")
        order.refresh_from_db()
        self.assertIsNotNone(order.notifications_sent_at)
        self.assertFalse(
            order.notification_deliveries.exclude(
                status=OrderNotificationDelivery.STATUS_SENT,
            ).exists()
        )

    def test_checkout_without_confirmation_is_blocked(self):
        response = post_json(self.client, "/cart/checkout/", {
            "name": "Зеленіна Оксана",
            "phone": "0503964141",
            "email": "buyer@example.com",
            "selectedDelivery": "artmagic_department",
            "selectedPayment": "payment_card",
            "products": [{"id": self.product.id, "quantity": 1, "preorder": 0}],
            "client_request_id": str(uuid.uuid4()),
        })
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Order.objects.count(), 0)

    @override_settings(**{**TEST_SETTINGS, "ORDER_CHECKOUT_V2": False})
    def test_feature_flag_fallback_accepts_new_frontend_payload(self):
        quote = self.quote(quantity=2)
        response = self.checkout(quote, price="1.00")
        self.assertEqual(response.status_code, 200, response.content)
        order = Order.objects.get()
        self.assertEqual(order.total_price, Decimal("380.00"))
        self.assertEqual(order.status, Order.STATUS_NEW)
        self.assertEqual(StockReservation.objects.count(), 0)

    @override_settings(**{**TEST_SETTINGS, "ORDER_CHECKOUT_V2": False})
    def test_old_client_double_click_reuses_server_request_id(self):
        payload = {
            "name": "Старий клієнт",
            "phone": "0500000000",
            "email": "old@example.com",
            "products": [{
                "id": self.product.id,
                "price": "190.00",
                "quantity": 1,
                "preorder": 0,
            }],
            "selectedDelivery": "artmagic_department",
            "selectedPayment": "payment_card",
        }
        first = post_json(self.client, "/cart/process-order/", payload)
        second = post_json(self.client, "/cart/process-order/", payload)
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(first.json()["orderNumber"], second.json()["orderNumber"])
        self.assertEqual(Order.objects.count(), 1)

    @override_settings(**{**TEST_SETTINGS, "ORDER_CHECKOUT_V2": False})
    def test_old_liqpay_endpoints_return_same_order(self):
        old_payload = {
            "fullName": {"value": "Старий клієнт"},
            "clientPhone": {"value": "0500000000"},
            "email": {"value": "old@example.com"},
            "city": {"value": ""},
            "address": {"value": ""},
            "area": {"value": ""},
            "department": {"value": ""},
            "products": [{
                "id": self.product.id,
                "name": self.product.name,
                "model": self.product.model,
                "price": "1.00",
                "quantity": 1,
                "preorder": 0,
            }],
            "selectedDelivery": "artmagic_department",
            "selectedPayment": "liqpay",
        }
        with self.captureOnCommitCallbacks(execute=True):
            first = post_json(self.client, "/payment/create/", old_payload)
        self.assertEqual(first.status_code, 200, first.content)
        order_number = first.json()["orderNumber"]
        second_payload = {
            "name": "Старий клієнт",
            "phone": "0500000000",
            "email": "old@example.com",
            "products": old_payload["products"],
            "selectedDelivery": "artmagic_department",
            "selectedPayment": "liqpay",
            "orderNumber": order_number,
        }
        second = post_json(
            self.client,
            "/cart/process-order/",
            second_payload,
        )
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(second.json()["orderNumber"], order_number)
        self.assertEqual(Order.objects.count(), 1)


@override_settings(**TEST_SETTINGS)
class LastUnitRaceTests(TransactionTestCase):
    def test_two_buyers_cannot_reserve_the_same_unit(self):
        product = Products.objects.create(
            name="Остання одиниця",
            model="last-unit",
            price=Decimal("10.00"),
            quantity=1,
            status=True,
        )
        quote = post_json(self.client, "/cart/refresh/", {
            "items": [{"id": product.id, "requested_quantity": 1, "price": "10.00"}],
        }).json()

        def buy(request_id):
            return perform_checkout({
                "name": "Покупець",
                "phone": "0500000000",
                "email": f"{request_id.hex[:8]}@example.com",
                "selectedDelivery": "artmagic_department",
                "selectedPayment": "payment_card",
                "products": [{"id": product.id, "quantity": 1, "preorder": 0, "price": "10.00"}],
                "client_request_id": str(request_id),
                "confirmed_fingerprint": quote["fingerprint"],
            }, RequestUser())

        buy(uuid.uuid4())
        with self.assertRaises(CheckoutError) as caught:
            buy(uuid.uuid4())
        self.assertEqual(caught.exception.http_status, 409)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(StockReservation.objects.filter(status=StockReservation.STATUS_ACTIVE).count(), 1)
        self.assertEqual(StockReservation.objects.get().quantity, 1)

    def test_concurrent_same_request_id_returns_same_order(self):
        if connection.vendor != "postgresql":
            self.skipTest("row-lock concurrency test requires PostgreSQL")
        product = Products.objects.create(
            name="Конкурентний товар",
            model="concurrent-idempotency",
            price=Decimal("15.00"),
            quantity=1,
            status=True,
        )
        quote = post_json(self.client, "/cart/refresh/", {
            "items": [{"id": product.id, "requested_quantity": 1}],
        }).json()
        request_id = uuid.uuid4()
        barrier = threading.Barrier(2)
        results = []

        def worker():
            connections.close_all()
            barrier.wait()
            try:
                results.append(perform_checkout({
                    "name": "Покупець",
                    "phone": "0500000000",
                    "email": "same@example.com",
                    "selectedDelivery": "artmagic_department",
                    "selectedPayment": "payment_card",
                    "products": [{
                        "id": product.id,
                        "quantity": 1,
                        "preorder": 0,
                        "price": "15.00",
                    }],
                    "client_request_id": str(request_id),
                    "confirmed_fingerprint": quote["fingerprint"],
                }, RequestUser()))
            except Exception as exc:
                results.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        errors = [result for result in results if isinstance(result, Exception)]
        self.assertEqual(errors, [], results)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(
            {result["orderNumber"] for result in results},
            {Order.objects.get().order_number},
        )
        self.assertEqual(StockReservation.objects.count(), 1)

    def test_concurrent_orders_receive_distinct_numbers(self):
        if connection.vendor != "postgresql":
            self.skipTest("order-number concurrency test requires PostgreSQL")
        products = [
            Products.objects.create(
                name=f"Товар {index}",
                model=f"concurrent-number-{index}",
                price=Decimal("12.00"),
                quantity=1,
                status=True,
            )
            for index in range(2)
        ]
        quotes = [
            post_json(self.client, "/cart/refresh/", {
                "items": [{"id": product.id, "requested_quantity": 1}],
            }).json()
            for product in products
        ]
        barrier = threading.Barrier(2)
        results = []

        def worker(index):
            connections.close_all()
            barrier.wait()
            try:
                results.append(perform_checkout({
                    "name": "Покупець",
                    "phone": "0500000000",
                    "email": f"number-{index}@example.com",
                    "selectedDelivery": "artmagic_department",
                    "selectedPayment": "payment_card",
                    "products": [{
                        "id": products[index].id,
                        "quantity": 1,
                        "preorder": 0,
                        "price": "12.00",
                    }],
                    "client_request_id": str(uuid.uuid4()),
                    "confirmed_fingerprint": quotes[index]["fingerprint"],
                }, RequestUser()))
            except Exception as exc:
                results.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        errors = [result for result in results if isinstance(result, Exception)]
        self.assertEqual(errors, [], results)
        self.assertEqual(Order.objects.count(), 2)
        self.assertEqual(Order.objects.values("order_number").distinct().count(), 2)


class RequestUser:
    def __init__(self):
        self.user = self
        self.is_authenticated = False

    def build_absolute_uri(self, path):
        return f"http://testserver{path}"


@override_settings(**TEST_SETTINGS)
class LiqPayTests(TestCase):
    def setUp(self):
        self.product = Products.objects.create(
            name="Оплата карткою",
            model="liqpay-item",
            price=Decimal("50.00"),
            quantity=2,
            status=True,
        )

    def start_payment(self):
        quote = post_json(self.client, "/cart/refresh/", {
            "items": [{"id": self.product.id, "quantity": 1, "preorder": 0, "price": "50.00"}],
        }).json()
        request_id = str(uuid.uuid4())
        with self.captureOnCommitCallbacks(execute=True):
            response = post_json(self.client, "/cart/checkout/", {
                "name": "Покупець",
                "phone": "0500000000",
                "email": "buyer@example.com",
                "selectedDelivery": "artmagic_department",
                "selectedPayment": "liqpay",
                "products": [{"id": self.product.id, "quantity": 1, "preorder": 0, "price": "1.00"}],
                "client_request_id": request_id,
                "confirmed_fingerprint": quote["fingerprint"],
            })
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("formHtml", response.json())
        self.assertIn("target=\"_blank\"", response.json()["formHtml"])
        return request_id, response.json()

    def callback(self, order, status, amount=None, currency="UAH"):
        payload = {
            "status": status,
            "amount": str(order.total_price) if amount is None else amount,
            "currency": currency,
            "order_id": f"{order.order_number}-artmagic_department",
            "payment_id": "pay-1",
        }
        raw = base64.b64encode(json.dumps(payload).encode()).decode()
        signature = base64.b64encode(
            hashlib.sha1(f"sandbox_private{raw}sandbox_private".encode()).digest()
        ).decode()
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post("/payment/liqpay-callback/", {"data": raw, "signature": signature})

    def test_success_failure_expiry_and_repeated_callback(self):
        request_id, first = self.start_payment()
        order = Order.objects.get()
        self.assertEqual(order.status, Order.STATUS_PENDING_PAYMENT)
        self.assertEqual(order.total_price, Decimal("50.00"))
        self.assertEqual(StockReservation.objects.get().status, StockReservation.STATUS_PENDING_PAYMENT)
        self.assertEqual(len(mail.outbox), 2)

        again = post_json(self.client, "/cart/checkout/", {
            "name": "Покупець",
            "phone": "0500000000",
            "email": "buyer@example.com",
            "selectedDelivery": "artmagic_department",
            "selectedPayment": "liqpay",
            "products": [{"id": self.product.id, "quantity": 1, "preorder": 0}],
            "client_request_id": request_id,
            "confirmed_fingerprint": "ignored",
        })
        self.assertEqual(again.json()["orderNumber"], first["orderNumber"])
        self.assertIn("formHtml", again.json())
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 2)

        failed = self.callback(order, "failure")
        self.assertEqual(failed.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_PAYMENT_FAILED)
        self.assertEqual(StockReservation.objects.get().status, StockReservation.STATUS_RELEASED)

    def test_success_is_idempotent_and_expiry_keeps_stock_free(self):
        self.start_payment()
        order = Order.objects.get()
        paid = self.callback(order, "success")
        self.assertEqual(paid.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_PAID)
        self.assertEqual(StockReservation.objects.get().status, StockReservation.STATUS_ACTIVE)
        self.assertEqual(len(mail.outbox), 4)
        repeat = self.callback(order, "success")
        self.assertEqual(repeat.status_code, 200)
        self.assertEqual(len(mail.outbox), 4)

        late_product = Products.objects.create(
            name="Прострочена оплата",
            model="late-pay",
            price=Decimal("20.00"),
            quantity=1,
            status=True,
        )
        quote = post_json(self.client, "/cart/refresh/", {
            "items": [{"id": late_product.id, "quantity": 1, "preorder": 0, "price": "20.00"}],
        }).json()
        with self.captureOnCommitCallbacks(execute=True):
            post_json(self.client, "/cart/checkout/", {
            "name": "Покупець",
            "phone": "0500000000",
            "email": "late@example.com",
            "selectedDelivery": "artmagic_department",
            "selectedPayment": "liqpay",
            "products": [{"id": late_product.id, "quantity": 1, "preorder": 0, "price": "20.00"}],
            "client_request_id": str(uuid.uuid4()),
            "confirmed_fingerprint": quote["fingerprint"],
        })
        late_order = Order.objects.get(email="late@example.com")
        reservation = late_order.reservations.get()
        reservation.expires_at = timezone.now() - timedelta(minutes=1)
        reservation.save(update_fields=["expires_at"])
        call_command("expire_stock_reservations")
        call_command("expire_stock_reservations")
        late_order.refresh_from_db()
        reservation.refresh_from_db()
        self.assertEqual(late_order.status, Order.STATUS_EXPIRED)
        self.assertEqual(reservation.status, StockReservation.STATUS_EXPIRED)
        sent_before = len(mail.outbox)
        self.callback(late_order, "success")
        late_order.refresh_from_db()
        reservation.refresh_from_db()
        self.assertEqual(late_order.status, Order.STATUS_PAID)
        self.assertEqual(reservation.status, StockReservation.STATUS_ACTIVE)
        self.assertEqual(len(mail.outbox), sent_before + 2)
        available = post_json(self.client, "/cart/refresh/", {
            "items": [{"id": late_product.id, "requested_quantity": 1}],
        }).json()["items"][0]["available"]
        self.assertEqual(available, 0)

    def test_invalid_signature_does_not_change_order(self):
        self.start_payment()
        order = Order.objects.get()
        response = self.client.post("/payment/liqpay-callback/", {"data": "e30=", "signature": "bad"})
        self.assertEqual(response.status_code, 403)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_PENDING_PAYMENT)
        self.assertEqual(len(mail.outbox), 2)

    def test_callback_validates_amount_and_currency(self):
        self.start_payment()
        order = Order.objects.get()
        wrong_amount = self.callback(order, "success", amount="1.00")
        wrong_currency = self.callback(order, "success", currency="USD")
        self.assertEqual(wrong_amount.status_code, 400)
        self.assertEqual(wrong_currency.status_code, 400)
        order.refresh_from_db()
        payment = Payment.objects.get(checkout_order=order)
        self.assertEqual(order.status, Order.STATUS_PENDING_PAYMENT)
        self.assertEqual(payment.status, "pending")
        self.assertEqual(
            StockReservation.objects.get().status,
            StockReservation.STATUS_PENDING_PAYMENT,
        )

    def test_out_of_order_callbacks_preserve_success_and_restore_stock(self):
        self.start_payment()
        order = Order.objects.get()
        self.callback(order, "failure")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_PAYMENT_FAILED)
        self.assertEqual(
            StockReservation.objects.get().status,
            StockReservation.STATUS_RELEASED,
        )

        self.callback(order, "success")
        order.refresh_from_db()
        payment = Payment.objects.get(checkout_order=order)
        reservation = StockReservation.objects.get()
        self.assertEqual(order.status, Order.STATUS_PAID)
        self.assertEqual(payment.status, "success")
        self.assertEqual(reservation.status, StockReservation.STATUS_ACTIVE)

        self.callback(order, "failure")
        order.refresh_from_db()
        payment.refresh_from_db()
        reservation.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_PAID)
        self.assertEqual(payment.status, "success")
        self.assertEqual(reservation.status, StockReservation.STATUS_ACTIVE)

    def test_all_preorder_liqpay_order_expires(self):
        self.product.quantity = 0
        self.product.save(update_fields=["quantity"])
        quote = post_json(self.client, "/cart/refresh/", {
            "items": [{
                "id": self.product.id,
                "quantity": 0,
                "preorder": 1,
                "price": "50.00",
            }],
        }).json()
        with self.captureOnCommitCallbacks(execute=True):
            response = post_json(self.client, "/cart/checkout/", {
                "name": "Покупець",
                "phone": "0500000000",
                "email": "preorder@example.com",
                "selectedDelivery": "artmagic_department",
                "selectedPayment": "liqpay",
                "products": [{
                    "id": self.product.id,
                    "quantity": 0,
                    "preorder": 1,
                    "price": "50.00",
                }],
                "client_request_id": str(uuid.uuid4()),
                "confirmed_fingerprint": quote["fingerprint"],
            })
        self.assertEqual(response.status_code, 200)
        order = Order.objects.get()
        self.assertEqual(order.reservations.count(), 0)
        Order.objects.filter(pk=order.pk).update(
            created_at=timezone.now() - timedelta(hours=1)
        )
        call_command("expire_stock_reservations")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_EXPIRED)
        self.assertEqual(
            Payment.objects.get(checkout_order=order).status,
            "expired",
        )

    def test_late_payment_without_available_stock_is_flagged(self):
        self.product.quantity = 1
        self.product.save(update_fields=["quantity"])
        self.start_payment()
        old_order = Order.objects.get()
        reservation = old_order.reservations.get()
        reservation.expires_at = timezone.now() - timedelta(minutes=1)
        reservation.save(update_fields=["expires_at"])
        call_command("expire_stock_reservations")

        quote = post_json(self.client, "/cart/refresh/", {
            "items": [{
                "id": self.product.id,
                "quantity": 1,
                "preorder": 0,
                "price": "50.00",
            }],
        }).json()
        with self.captureOnCommitCallbacks(execute=True):
            second = post_json(self.client, "/cart/checkout/", {
                "name": "Інший покупець",
                "phone": "0500000001",
                "email": "second@example.com",
                "selectedDelivery": "artmagic_department",
                "selectedPayment": "payment_card",
                "products": [{
                    "id": self.product.id,
                    "quantity": 1,
                    "preorder": 0,
                    "price": "50.00",
                }],
                "client_request_id": str(uuid.uuid4()),
                "confirmed_fingerprint": quote["fingerprint"],
            })
        self.assertEqual(second.status_code, 200, second.content)

        self.callback(old_order, "success")
        old_order.refresh_from_db()
        reservation.refresh_from_db()
        self.assertEqual(
            old_order.status,
            Order.STATUS_PAID_STOCK_CONFLICT,
        )
        self.assertEqual(
            reservation.status,
            StockReservation.STATUS_EXPIRED,
        )


@override_settings(**TEST_SETTINGS)
class OneCSyncTests(TestCase):
    def setUp(self):
        self.product = Products.objects.create(
            name="Товар 1С",
            model="sync-1",
            price=Decimal("100.00"),
            quantity=5,
            status=True,
        )

    def sync(self, payload):
        return self.client.post(
            "/sync-products/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_1C_API_KEY="test-onec-key",
        )

    def test_full_partial_and_repeated_import(self):
        ok = self.sync([{"model": "sync-1", "name": "Товар 1С", "price": 80, "quantity": 4}])
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["status"], SyncRun.STATUS_SUCCESS)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 4)
        self.assertEqual(self.product.price, Decimal("80.00"))

        partial = self.sync([
            {"model": "sync-1", "name": "Товар 1С", "price": 80, "quantity": 4},
            {"name": "без артикула"},
        ])
        self.assertEqual(partial.status_code, 207)
        self.assertEqual(partial.json()["summary"]["failed"], 1)
        self.assertEqual(Products.objects.filter(model="sync-1").count(), 1)

        failed = self.sync([{"name": "без артикула"}])
        self.assertEqual(failed.status_code, 400)
        self.assertEqual(failed.json()["status"], SyncRun.STATUS_FAILED)

    def test_invalid_numbers_do_not_overwrite_product(self):
        fractional = self.sync([{
            "model": "sync-1",
            "name": "Товар 1С",
            "price": 80,
            "quantity": 1.5,
        }])
        negative = self.sync([{
            "model": "sync-1",
            "name": "Товар 1С",
            "price": -1,
            "quantity": 2,
        }])
        self.assertEqual(fractional.status_code, 400)
        self.assertEqual(negative.status_code, 400)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 5)
        self.assertEqual(self.product.price, Decimal("100.00"))

    def test_reconciliation_failure_is_not_reported_as_success(self):
        with patch(
            "products.views.reconcile_pending_reservations",
            side_effect=RuntimeError("reconcile failed"),
        ):
            response = self.sync([{
                "model": "sync-1",
                "name": "Товар 1С",
                "price": 100,
                "quantity": 4,
            }])
        self.assertEqual(response.status_code, 207)
        self.assertEqual(response.json()["status"], SyncRun.STATUS_PARTIAL)
        self.assertEqual(response.json()["summary"]["failed"], 1)

    def test_active_reservation_survives_import_and_reconciles_after_1c(self):
        quote = post_json(self.client, "/cart/refresh/", {
            "items": [{"id": self.product.id, "quantity": 1, "preorder": 0, "price": "100.00"}],
        }).json()
        checkout = post_json(self.client, "/cart/checkout/", {
            "name": "Покупець",
            "phone": "0500000000",
            "email": "buyer@example.com",
            "selectedDelivery": "artmagic_department",
            "selectedPayment": "payment_card",
            "products": [{"id": self.product.id, "quantity": 1, "preorder": 0, "price": "100.00"}],
            "client_request_id": str(uuid.uuid4()),
            "confirmed_fingerprint": quote["fingerprint"],
        })
        self.assertEqual(checkout.status_code, 200, checkout.content)
        self.sync([{"model": "sync-1", "name": "Товар 1С", "price": 100, "quantity": 5}])
        reservation = StockReservation.objects.get()
        self.assertEqual(reservation.status, StockReservation.STATUS_ACTIVE)
        available = post_json(self.client, "/cart/refresh/", {
            "items": [{"id": self.product.id, "requested_quantity": 1}],
        }).json()["items"][0]["available"]
        self.assertEqual(available, 4)

        mark_entered_in_1c(Order.objects.get(), "manager")
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, StockReservation.STATUS_PENDING_1C)
        self.sync([{"model": "sync-1", "name": "Товар 1С", "price": 100, "quantity": 4}])
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, StockReservation.STATUS_RECONCILED)
        available_after = post_json(self.client, "/cart/refresh/", {
            "items": [{"id": self.product.id, "requested_quantity": 1}],
        }).json()["items"][0]["available"]
        self.assertEqual(available_after, 4)
        self.sync([{"model": "sync-1", "name": "Товар 1С", "price": 100, "quantity": 4}])
        self.assertEqual(Products.objects.filter(model="sync-1").count(), 1)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, StockReservation.STATUS_RECONCILED)

    def test_import_started_before_admin_mark_cannot_reconcile(self):
        quote = post_json(self.client, "/cart/refresh/", {
            "items": [{
                "id": self.product.id,
                "quantity": 1,
                "preorder": 0,
                "price": "100.00",
            }],
        }).json()
        post_json(self.client, "/cart/checkout/", {
            "name": "Покупець",
            "phone": "0500000000",
            "email": "buyer@example.com",
            "selectedDelivery": "artmagic_department",
            "selectedPayment": "payment_card",
            "products": [{
                "id": self.product.id,
                "quantity": 1,
                "preorder": 0,
                "price": "100.00",
            }],
            "client_request_id": str(uuid.uuid4()),
            "confirmed_fingerprint": quote["fingerprint"],
        })
        order = Order.objects.get()
        import_started = timezone.now() - timedelta(seconds=1)
        mark_entered_in_1c(order, "manager")
        reservation = StockReservation.objects.get()
        reconcile_pending_reservations([self.product.id], import_started)
        reservation.refresh_from_db()
        self.assertEqual(
            reservation.status,
            StockReservation.STATUS_PENDING_1C,
        )
        reconcile_pending_reservations(
            [self.product.id],
            timezone.now() + timedelta(seconds=1),
        )
        reservation.refresh_from_db()
        self.assertEqual(
            reservation.status,
            StockReservation.STATUS_RECONCILED,
        )

    def test_missing_sync_is_stale_until_a_recent_success(self):
        self.assertTrue(is_sync_stale())
        SyncRun.objects.create(
            sync_id=uuid.uuid4(),
            started_at=timezone.now() - timedelta(days=3),
            finished_at=timezone.now() - timedelta(days=3),
            status=SyncRun.STATUS_SUCCESS,
        )
        self.assertTrue(is_sync_stale())
        SyncRun.objects.create(
            sync_id=uuid.uuid4(),
            started_at=timezone.now(),
            finished_at=timezone.now(),
            status=SyncRun.STATUS_SUCCESS,
        )
        self.assertFalse(is_sync_stale())
