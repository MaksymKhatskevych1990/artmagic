import logging
from django.conf import settings
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from .models import Payment
from users.models import CustomUser, Address
from liqpay.liqpay3 import LiqPay
from datetime import datetime
from django.http import JsonResponse, HttpRequest
from django.forms.models import model_to_dict
import time
import json


from carts.checkout import CheckoutError, handle_liqpay_callback, perform_checkout
from carts.utils import parse_request_data, get_delivery_info, validate_required_fields, create_order, prepare_email_context, send_email, prepare_email_context_liqpay
from artmagic.settings import EMAIL_HOST_USER
logger = logging.getLogger(__name__)


def create_payment(request):
    if request.method != 'POST':
        return HttpResponse("GET method not supported for payment creation", status=405)
    try:
        data = parse_request_data(request)
        result = perform_checkout(data, request)
        http_status = 409 if result.get("status") == "stock_changed" else 200
        return JsonResponse(result, status=http_status)
    except CheckoutError as exc:
        return JsonResponse(exc.payload, status=exc.http_status)
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Некоректний JSON"}, status=400)
    except Exception:
        logger.exception("create_payment_failed")
        return JsonResponse({"status": "error", "message": "Не вдалося створити оплату"}, status=500)
# def create_payment(request):

from django.views.decorators.csrf import csrf_exempt
import base64
import hashlib
import hmac
import json
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from liqpay.liqpay3 import LiqPay
from django.conf import settings
import logging


@csrf_exempt
def payment_status(request):

    

    email_owner = EMAIL_HOST_USER
    data = request.POST.get('data', '')
    signature = request.POST.get('signature', '')
    expected_signature = base64.b64encode(
        hashlib.sha1(f"{settings.LIQPAY_PRIVATE_KEY}{data}{settings.LIQPAY_PRIVATE_KEY}".encode()).digest()
    ).decode()
    
    if not hmac.compare_digest(signature, expected_signature):
        logger.warning("liqpay_callback signature=invalid")
        return HttpResponse("Invalid signature", status=403)

    try:
        decoded_data = json.loads(base64.b64decode(data).decode("utf-8"))
    except Exception:
        logger.warning("liqpay_callback bad_payload")
        return HttpResponse("Bad payload", status=400)

    try:
        result = handle_liqpay_callback(decoded_data)
    except Exception:
        logger.exception("liqpay_callback_failed")
        return HttpResponse("Error", status=500)
    if result == "missing":
        return HttpResponse("Payment not found", status=404)
    if result == "mismatch":
        return HttpResponse("Payment data mismatch", status=400)
    return HttpResponse("OK", status=200)
