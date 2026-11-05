from carts.models import Cart
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from carts.models import Cart
from django.views import View
from carts.models import Order, PreOrder
from django.core.exceptions import ObjectDoesNotExist

from django.core.mail import send_mail
from django.core.mail import EmailMessage
from products.models import Products
from delivery.models import DeliveryOption
from liqpay_app.models import Payment
from .decryption_ref import get_city_name, get_area_name, get_department_name
from openpyxl import Workbook
import os
from datetime import datetime
import json
import logging
from django.conf import settings


import json
from decimal import Decimal
from django.db import IntegrityError
from django.template.loader import render_to_string
from carts.models import Order, PreOrder
from .decryption_ref import get_city_name, get_area_name, get_department_name
from artmagic.settings import EMAIL_HOST_USER


logger = logging.getLogger(__name__)

def get_user_carts(request):
    if request.user.is_authenticated:
        return Cart.objects.filter(user=request.user).select_related('product')
    
    if not request.session.session_key:
        request.session.create()
    return Cart.objects.filter(session_key=request.session.session_key).select_related('product')


def parse_request_data(request):
    body_unicode = request.body.decode('utf-8')
    data = json.loads(body_unicode)
    return data

def get_delivery_info(data):
    delivery_options = {
        'artmagic_department': "Самовивіз",
        'new_post_department': "Відділення Нової пошти",
        'new_post_packing': "Поштомат Нової пошти",
        'new_post_address': "Кур'єрська доставка Нової пошти",
        'ukr_post': "Укрпошта"
    }


    data_delivery = data.get('selectedDelivery')
    delivery_method = delivery_options.get(data_delivery, "")
    address = data.get('address', '')
    # Установка адреса в зависимости от метода доставки
    if delivery_method == "Самовивіз":
        address = 'м. Дніпро, Вул. Якова Самарського 5, к. 7'
    elif delivery_method in ["Відділення Нової пошти", "Поштомат Нової пошти"]:
        area_value = get_area_name(data['area'])
        city_value = get_city_name(data['city'])
        department_value = get_department_name(data['department'], data['city'])
        address = f'{area_value} область, {city_value}, {department_value}'
    elif delivery_method == "Кур'єрська доставка Нової пошти":
        area_value = get_area_name(data['area'])
        city_value = get_city_name(data['city'])
        address = f'{area_value} область, {city_value}, {address}'
    
    return delivery_method, address

def validate_required_fields(data):
    required_fields = ['name', 'phone', 'email', 'products']
    if not all(data.get(field) for field in required_fields):
        raise ValueError('Missing required fields in data')

def create_order(data, user, address):

    payment_options = {
        'liqpay': "Онлайн-оплата банківською карткою",
        'payment_card': "Оплата за реквізитами",
        'payment_real': "Оплата у точці видачі"
    }
    # Создаем основной заказ
    selected_payment = payment_options.get(data.get('selectedPayment', ""), "")
    order = Order.objects.create(
        user=user,
        name=data.get('name'),
        phone=data.get('phone'),
        email=data.get('email'),
        payment=selected_payment,
        address=address,
        total_price=data.get('amount'),
        products=data.get('products')  # Сохранение продуктов как JSON-объект
    )
    prod_pre = data.get('products')
    preorder_items = []

    # Collect all pre-order items
    for item in prod_pre:
        if int(item.get('preorder') or 0) > 0:
            preorder_items.append({
                'model': item['model'],
                'name': item['name'],
                'price': item.get('price', item.get('unit_price')),
                'quantity': item['preorder']
            })

    # Create a single PreOrder with all pre-order items if any exist
    if preorder_items:
        try:
            PreOrder.objects.create(
                user=user,
                order=order,
                name=data.get('name'),
                products=preorder_items,
                quantity=sum(item['quantity'] for item in preorder_items)
            )
            logger.debug('Single PreOrder created successfully for all items: %s', preorder_items)
        except IntegrityError as e:
            logger.error('Failed to create PreOrder due to IntegrityError: %s', e)
        except Exception as e:
            logger.error('Failed to create PreOrder due to unexpected error: %s', e)

    return order

def prepare_email_context(data, delivery_method, address, order_number):

    payment_options = {
        'liqpay': "Онлайн-оплата банківською карткою",
        'payment_card': "Оплата за реквізитами",
        'payment_real': "Оплата у точці видачі"
    }

    prod_pre = data.get('products')
    preorder_list = []

    product_order = [el for el in prod_pre if el["quantity"] != 0]
    preorder_total_price = Decimal(0)

    for item in prod_pre:
        if 'preorder' in item and item['preorder'] != 0:
            preorder_list.append(item)
            price = Decimal(item['price'])  
            preorder_total_price += price * int(item['preorder'])

    preorder_total_price = preorder_total_price.quantize(Decimal('0.00'))
    return {
        'name': data.get('name'),
        'phone': data.get('phone'),
        'email': data.get('email'),
        'payment': payment_options.get(data.get('selectedPayment', ""), ""),
        'address': address,
        'products': product_order,
        'preorder_product': preorder_list,
        'preorder_total_price': preorder_total_price,
        'total_price': data.get('amount'),
        'delivery_method': delivery_method,
        'order_number': order_number
    }

def send_email(recipient, context, subject, template_path):

    email_owner = EMAIL_HOST_USER

    html_message = render_to_string(template_path, context)
    email_message = EmailMessage(subject, html_message, email_owner, [recipient])
    email_message.content_subtype = "html"
    email_message.send()
    logger.debug('Email sent successfully to %s', recipient)

def prepare_email_context_liqpay(decoded_data, order_id):
    delivery_options = {
        'artmagic_department': "Самовивіз",
        'new_post_department': "Відділення Нової пошти",
        'new_post_packing': "Поштомат Нової пошти",
        'new_post_address': "Кур'єрська доставка Нової пошти",
        'ukr_post': "Укрпошта"
    }

    if order_id:
        try:
            order_data = Order.objects.get(order_number=order_id)
        except ObjectDoesNotExist:
            print(f"Order with order_number={order_id} not found.")

        try:
            pre_order_data = PreOrder.objects.get(order_number=order_id)
        except ObjectDoesNotExist:
            print(f"PreOrder with order_number={order_id} not found.")



    preorder_total_price = Decimal('0.00')
    pre_order_products = pre_order_data.products
    for item in pre_order_products:
        item['preorder'] = item.pop('quantity')
        
        price = Decimal(item['price'])
        preorder_total_price += price * int(item['preorder'])

    preorder_total_price = preorder_total_price.quantize(Decimal('0.00'))
    # Добавление preorder_total_price в fields
    selected_delivery = decoded_data.get('order_id', None).split('-')[1]
    delivery_method = delivery_options.get(selected_delivery, "")
    fields = {
        'order_number': order_id,
        'name': order_data.name,
        'phone': order_data.phone,
        'email': order_data.email,
        'payment': order_data.payment,
        'address': order_data.address,
        'products': order_data.products,        
        'delivery_method': delivery_method,
        'preorder_product': pre_order_products,
        'preorder_total_price': preorder_total_price,
        'total_price': order_data.total_price
    }
    email = order_data.email

    return fields, email