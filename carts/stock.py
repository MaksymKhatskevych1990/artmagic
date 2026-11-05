import hashlib
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db.models import Sum

from carts.models import StockReservation
from products.models import Products

logger = logging.getLogger("carts.stock")

MAX_LINES = 50
MAX_QTY = 999


class StockError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(message)


def checkout_enabled():
    return getattr(settings, "ORDER_CHECKOUT_V2", True)


def reservation_minutes():
    return int(getattr(settings, "STOCK_RESERVATION_MINUTES", 30))


def as_money(value):
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None


def money_str(value):
    amount = as_money(value)
    if amount is None:
        amount = Decimal("0.00")
    return f"{amount:.2f}"


def _whole_quantity(value, label="Кількість"):
    if isinstance(value, bool) or value is None:
        raise StockError(f"{label} має бути цілим числом")
    if isinstance(value, float):
        if not value.is_integer():
            raise StockError(f"{label} має бути цілим числом")
        value = int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or any(char in stripped for char in ".eE"):
            raise StockError(f"{label} має бути цілим числом")
        try:
            value = int(stripped)
        except ValueError as exc:
            raise StockError(f"{label} має бути цілим числом") from exc
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise StockError(f"{label} має бути цілим числом") from exc
    if value < 0:
        raise StockError("Кількість не може бути від'ємною")
    if value > MAX_QTY:
        raise StockError("Занадто велика кількість товару")
    return value


def parse_cart_items(raw_items):
    if not isinstance(raw_items, list) or not raw_items:
        raise StockError("Кошик порожній")

    merged = {}
    order = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise StockError("Некоректна позиція кошика")
        try:
            product_id = int(raw.get("id"))
        except (TypeError, ValueError) as exc:
            raise StockError("Некоректний товар у кошику") from exc

        if raw.get("requested_quantity") is not None:
            requested = _whole_quantity(raw.get("requested_quantity"))
            client_quantity = None
            client_preorder = None
        else:
            client_quantity = _whole_quantity(raw.get("quantity") or 0)
            client_preorder = _whole_quantity(raw.get("preorder") or 0)
            requested = client_quantity + client_preorder
            if requested > MAX_QTY:
                raise StockError("Занадто велика кількість товару")

        if requested == 0:
            continue

        client_price = raw.get("price", raw.get("unit_price"))
        if product_id not in merged:
            order.append(product_id)
            merged[product_id] = {
                "id": product_id,
                "requested": 0,
                "client_quantity": 0 if client_quantity is not None else None,
                "client_preorder": 0 if client_preorder is not None else None,
                "knows_split": client_quantity is not None,
                "client_price": client_price,
            }
        current = merged[product_id]
        current["requested"] += requested
        if current["requested"] > MAX_QTY:
            raise StockError("Занадто велика кількість товару")
        if client_quantity is not None:
            if current["client_quantity"] is None:
                current["client_quantity"] = 0
                current["client_preorder"] = 0
                current["knows_split"] = True
            current["client_quantity"] += client_quantity
            current["client_preorder"] += client_preorder
        if client_price is not None:
            current["client_price"] = client_price

    if not order:
        raise StockError("Кошик порожній")
    if len(order) > MAX_LINES:
        raise StockError("Забагато позицій у кошику")
    return [merged[product_id] for product_id in order]


def reserved_quantities(product_ids):
    if not product_ids or not checkout_enabled():
        return {}
    rows = (
        StockReservation.objects.filter(
            product_id__in=product_ids,
            status__in=StockReservation.HOLDING_STATUSES,
        )
        .values("product_id")
        .annotate(total=Sum("quantity"))
    )
    return {row["product_id"]: int(row["total"] or 0) for row in rows}


def quote_cart(raw_items):
    parsed = parse_cart_items(raw_items)
    product_ids = [item["id"] for item in parsed]
    products = {product.id: product for product in Products.objects.filter(id__in=product_ids)}
    reserved = reserved_quantities(product_ids)
    lines = []
    changed = False
    total = Decimal("0.00")
    preorder_total = Decimal("0.00")

    for item in parsed:
        product = products.get(item["id"])
        if product is None:
            changed = True
            lines.append(_empty_line(item, "not_found"))
            continue
        if product.status is False:
            changed = True
            lines.append(_empty_line(item, "disabled", product))
            continue

        external_qty = product.quantity or 0
        if external_qty < 0:
            external_qty = 0
        available = max(int(external_qty) - int(reserved.get(product.id, 0)), 0)
        in_stock = min(item["requested"], available)
        preorder = item["requested"] - in_stock
        unit_price = as_money(product.price) or Decimal("0.00")
        client_price = as_money(item["client_price"]) if item["client_price"] is not None else None
        price_changed = client_price is not None and client_price != unit_price
        if item["knows_split"]:
            stock_changed = (
                item["client_quantity"] != in_stock or item["client_preorder"] != preorder
            )
        else:
            stock_changed = in_stock != item["requested"]
        if price_changed or stock_changed:
            changed = True
        total += unit_price * in_stock
        preorder_total += unit_price * preorder
        lines.append({
            "id": product.id,
            "model": product.model or "",
            "name": product.name or "",
            "unit_price": money_str(unit_price),
            "requested_quantity": item["requested"],
            "quantity": in_stock,
            "preorder": preorder,
            "available": available,
            "price_changed": price_changed,
            "stock_changed": stock_changed,
            "unavailable": False,
            "reason": "",
            "stock_quantity_at_checkout": int(external_qty),
            "reserved_quantity": in_stock,
        })

    payload = {
        "status": "success",
        "changed": changed,
        "items": [_public_line(line) for line in lines],
        "total": money_str(total),
        "preorder_total": money_str(preorder_total),
        "fingerprint": fingerprint(lines),
    }
    payload["_lines"] = lines
    return payload


def fingerprint(lines):
    parts = []
    for line in sorted(lines, key=lambda item: item["id"]):
        parts.append(
            "|".join([
                str(line["id"]),
                str(line.get("unit_price", "0.00")),
                str(line.get("quantity", 0)),
                str(line.get("preorder", 0)),
                "1" if line.get("unavailable") else "0",
            ])
        )
    return hashlib.sha256(";".join(parts).encode("utf-8")).hexdigest()


def public_quote(raw_items):
    quote = quote_cart(raw_items)
    quote.pop("_lines", None)
    return quote


def reconcile_pending_reservations(product_ids, sync_started_at):
    if not product_ids:
        return 0
    updated = StockReservation.objects.filter(
        product_id__in=list(product_ids),
        status=StockReservation.STATUS_PENDING_1C,
        # A reservation marked while this import was already running must wait
        # for the next import, which is guaranteed to contain the 1C change.
        updated_at__lte=sync_started_at,
    ).update(status=StockReservation.STATUS_RECONCILED)
    if updated:
        logger.info("reservations_reconciled count=%s", updated)
    return updated


def _empty_line(item, reason, product=None):
    return {
        "id": item["id"],
        "model": getattr(product, "model", "") or "",
        "name": getattr(product, "name", "") or "",
        "unit_price": money_str(getattr(product, "price", 0) or 0),
        "requested_quantity": item["requested"],
        "quantity": 0,
        "preorder": 0,
        "available": 0,
        "price_changed": False,
        "stock_changed": True,
        "unavailable": True,
        "reason": reason,
        "stock_quantity_at_checkout": int(getattr(product, "quantity", 0) or 0) if product else 0,
        "reserved_quantity": 0,
    }


def _public_line(line):
    return {
        "id": line["id"],
        "model": line["model"],
        "name": line["name"],
        "unit_price": line["unit_price"],
        "requested_quantity": line["requested_quantity"],
        "quantity": line["quantity"],
        "preorder": line["preorder"],
        "available": line["available"],
        "price_changed": line["price_changed"],
        "stock_changed": line["stock_changed"],
        "unavailable": line["unavailable"],
        "reason": line["reason"],
    }
