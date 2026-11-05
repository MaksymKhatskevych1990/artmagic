import re  # Обновлено
import json
import uuid
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.views import View
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.response import Response
from unidecode import unidecode    
from django.utils.text import slugify
from django.utils.html import strip_tags
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied

import logging


from .models import (Products,
                     Category,
                     ProductToCategory,  # Обновлено
                     Manufacturer,
                     ProductFilter,  # Обновлено
                     FilterCategory,  # Обновлено
                     FilterValue,
                     ProductImage,
                     Stocks,
                     SyncRun)  # Обновлено
from main.models import Carousel, ContactInfo, Informations
from django.conf import settings
from .filters import build_facet_options, filter_products
from .sync import record_sync_run
from carts.stock import reconcile_pending_reservations
from .utils import alphanumeric_sort, get_sorted_product_attributes


logger = logging.getLogger(__name__)

def get_subcategories(request, parent_id):
    subcategories = Category.objects.filter(parent_id=parent_id)
    data = {
        'subcategories': [{'id': sub.id, 'name': sub.name} for sub in subcategories]
    }
    return JsonResponse(data)


def update_filter_data_on_change(request, group_id):
    # Получаем данные из запроса
    product_id = request.GET.get('product_id')
    category_id = request.GET.get('category_id')
    value_id = request.GET.get('value_id')
    # Устанавливаем выбранную категорию и значение, если они указаны
    selected_category_id = int(category_id) if category_id else None
    selected_value_id = int(value_id) if value_id else None

    # Получаем категории фильтров, связанные с группой
    if group_id == 0:
        filter_categories = FilterCategory.objects.all().order_by('name')
    else:
        filter_categories = FilterCategory.objects.filter(group_id=group_id).order_by('name')

    # Формируем список категорий, выделяя выбранную категорию
    categories = [{
        'id': category.id,
        'name': category.name,
        'selected': category.id == selected_category_id
    } for category in filter_categories]
    if not category_id:
        category_id = None
        # category_id = categories[0]['id']
    # Получаем значения фильтров только для выбранной категории, если она указана
    values = []
    if category_id:
        filter_values = FilterValue.objects.filter(category_id=category_id)
        sorted_filter_values = sorted(filter_values, key=lambda fv: alphanumeric_sort(fv.value))
        values = [{
            'id': value.id,
            'value': value.value,
            'selected': value.id == selected_value_id
        } for value in sorted_filter_values]

    # Возвращаем категории и значения в формате JSON
    return JsonResponse({'categories': categories, 'values': values})



def load_initial_filter_data(request, group_id):
    # Получаем данные из запроса
    product_id = request.GET.get('product_id')
    category_id = request.GET.get('category_id')
    value_id = request.GET.get('value_id')
    # Проверка на наличие выбранного значения категории
    selected_category_id = int(category_id) if category_id else None
    selected_value_id = int(value_id) if value_id else None

    # Получаем список категорий фильтров, связанных с текущей группой
    if group_id == 0:
        filter_categories = FilterCategory.objects.all().order_by('name')
    else:
        filter_categories = FilterCategory.objects.filter(group_id=group_id).order_by('name')

    # Если product_id, category_id и value_id указаны, проверяем, есть ли такая запись в ProductFilter
    if product_id and category_id and value_id:
        try:
            product_filter = ProductFilter.objects.get(
                product_id=product_id, 
                filter_category_id=category_id, 
                filter_value_id=value_id
            )
            # Устанавливаем выбранные категории и значения
            selected_category_id = product_filter.filter_category_id
            selected_value_id = product_filter.filter_value_id
        except ProductFilter.DoesNotExist:
            # Если не найдено, ничего не меняем, используем текущие значения
            print("ProductFilter для указанных данных не найден.")

    # Формируем список категорий с учетом выбранной
    categories = [{
        'id': category.id,
        'name': category.name,
        'selected': category.id == selected_category_id
    } for category in filter_categories]
    
    # Получаем значения для выбранной категории, если она указана
    values = []
    if category_id:
        filter_values = FilterValue.objects.filter(category_id=category_id)
        sorted_filter_values = sorted(filter_values, key=lambda fv: alphanumeric_sort(fv.value))
        values = [{
            'id': value.id,
            'value': value.value,
            'selected': value.id == selected_value_id
        } for value in sorted_filter_values]
    # Возвращаем категории и значения в формате JSON
    return JsonResponse({'categories': categories, 'values': values})

def add_to_cart(request):
    product_id = int(request.GET["id"])
    try:
        product = get_object_or_404(Products, pk=product_id)
        
        json_data = {
            'id': product.id,
            'name': product.name,
            'image': f'{product.image}' if not product.image else f'/media/{product.image}',
            'price': product.price,
            'model': product.model,
            'storageQuantity': product.quantity,
            'preorder': None
        }
        print(json_data)
        return JsonResponse(json_data, safe=False)
    except Products.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)


def parent_categories(request):
    categories = list(Category.objects.filter(parent=None).order_by('name'))
    for category in categories:
        image = category.image
        if not image:
            child = (
                category.get_descendants()
                .exclude(image='')
                .exclude(image__isnull=True)
                .order_by('lft')
                .first()
            )
            image = child.image if child else None
        category.home_image = image
    stocks = Stocks.objects.all()
    carousel = Carousel.objects.all()
    informations = Informations.objects.first()
    
    if informations:
        informations.description = (informations.description or '').replace('&nbsp;', '')


    return render(request, 'products/index.html', {'categories': categories, 'stocks': stocks, 'carousel': carousel, 'informations': informations})

class SubCategoriesView(View):
    template_name = 'products/category.html'
    
    def get(self, request, slug):
        parent_category = get_object_or_404(Category, slug=slug)
        try:
            
            parent_category.description = (parent_category.description or '').replace('&nbsp;', '')
            sub_categories = parent_category.children.all()

            breadcrumbs = [
                {'name': 'Головна', 'url': '/'},
                {'name': parent_category.name, 'url': request.path},
            ]

            descendants = parent_category.get_descendants(include_self=True)
            category_ids = [descendant.pk for descendant in descendants]

            products = Products.objects.filter(
                producttocategory__category_id__in=category_ids
            ).distinct()

        except Exception as e:
            logger.error(f"Ошибка при получении данных категории: {e}")
            return JsonResponse({'error': 'Ошибка загрузки данных категории'}, status=500)

        if 'add-category' in request.path:
            try:
                products_values = products.values('id', 'name', 'image', 'price', 'model')
                paginate_by = int(request.GET.get('productsPerPage', 10))
                paginator = Paginator(products_values, paginate_by)
                page_number = request.GET.get('page', 1)
                page_obj = paginator.get_page(page_number)

                products_data = list(page_obj)
                for product in products_data:
                    if product.get('image'):
                        product['image'] = "/media/" + product['image']
                    else:
                        product['image'] = ""

                json_data = {
                    'products': products_data,
                    'productsPerPage': paginator.per_page,
                    'productsAmount': paginator.count,
                    'currentPage': page_obj.number,
                }
                return JsonResponse(json_data)
            except Exception as e:
                logger.error(f"Ошибка при обработке продуктов или пагинации: {e}")
                return JsonResponse({'error': 'Ошибка загрузки продуктов'}, status=500)
        else:
            return render(request, self.template_name, {
                'parent_category': parent_category,
                'sub_categories': sub_categories,
                'breadcrumbs': breadcrumbs
            })


class SubProductView(View):
    template_name = 'products/catalog.html'

    def get(self, request, slug):
        parent_category = None
        breadcrumbs = [{'name': 'Головна', 'url': '/'}]
        searchquery = request.GET.get('query', '')

        if slug != 'search':
            parent_category = get_object_or_404(Category, slug=slug)
            parent_category.description = (parent_category.description or '').replace('&nbsp;', '')
            

        if parent_category:
            product_ids = ProductToCategory.objects.filter(category_id=parent_category.pk).values_list('product_id',
                                                                                                       flat=True)
            
            parent_of_parent_category = parent_category.parent
            products = Products.objects.filter(id__in=product_ids).distinct()
            if parent_of_parent_category:
                breadcrumbs.append({'name': parent_of_parent_category.name, 'url': parent_of_parent_category.get_absolute_url()})

            breadcrumbs.append({'name': parent_category.name, 'url': request.path})
        else:
            products = Products.objects.all().distinct()
            
            breadcrumbs = [
                {'name': 'Головна', 'url': '/'},
                {'name': "Пошук", 'url': ''},  # Текущая категория
            ]

        is_filters_request = 'add-filters' in request.path
        try:
            page_number = max(1, int(request.GET.get('page', 1)))
        except (TypeError, ValueError):
            page_number = 1

        # Facets only change with filter/search selection, not pagination.
        # Skip rebuild on page > 1 AJAX; frontend keeps the sidebar from page 1.
        need_facets = not (is_filters_request and page_number > 1)
        filters = build_facet_options(products, request.GET) if need_facets else None

        filtered_queryset = filter_products(products, request.GET)
        filtered_queryset = filtered_queryset.values('id', 'name', 'image', 'price', 'model')

        # Пагинация
        paginate_by = request.GET.get('productsPerPage', 10)
        paginator = Paginator(filtered_queryset, paginate_by)
        page_obj = paginator.get_page(page_number)

        if is_filters_request:
            products_data = list(page_obj)
            for product in products_data:
                if product['image']:
                    product['image'] = "/media/" + product['image']
            return JsonResponse({
                'products': products_data,
                'productsPerPage': paginator.per_page,
                'productsAmount': paginator.count,
                'currentPage': page_obj.number,
                'filters': filters,
            })

        if paginator.count == 0:
            return render(request, 'products/not_find_products.html', {
                'parent_category': parent_category,
                'filters': filters,
                'breadcrumbs': breadcrumbs,
                'searchquery': searchquery,
            })

        return render(request, self.template_name, {
            'parent_category': parent_category,
            'filters': filters,
            'breadcrumbs': breadcrumbs,
            'searchquery': searchquery,
        })


def get_new_arrivals(request):
    products = list(Products.objects.order_by('-date_added')[:24].values('name', 'image', 'price', 'pk', 'model'))

    paginate_by = request.GET.get('productsPerPage', 10)
    page_number = request.GET.get('page', 1)

    paginator = Paginator(products, paginate_by)
    page_obj = paginator.get_page(page_number)

    # Переименовать ключ 'pk' на 'id'
    products_data = [
        {'name': product['name'], 'image': product['image'], 'price': product['price'], 'id': product['pk']}
        for product in page_obj
    ]
    for product in products_data:
        if not product['image']:
            product['image']
        else:
            product['image'] = "/media/" + product['image']
    json_data = {
        'products': products_data,
        'productsPerPage': paginator.per_page,
        'productsAmount': paginator.count,  # Добавить общее количество продуктов
    }
    return JsonResponse(json_data)


class DetaileProductView(View):
    template_name = 'products/detaile.html'

    def get(self, request, id):        
        
        product = get_object_or_404(Products, id=id)
        product.description = (product.description or '').replace('&nbsp;', '')
        product_attribute = ProductFilter.objects.filter(product_id=product.pk)
        
        attributes = get_sorted_product_attributes(product_attribute)

        images = ProductImage.objects.filter(product=product.pk)
        all_images = self.build_images(product, images)
        
        categories = ProductToCategory.objects.filter(product_id=product.id).select_related('category_id')
        breadcrumbs = self.get_breadcrumbs(categories)

        if product.image:
            image_address = f"https://artmagic.com.ua/media/{product.image}"
        else:
            image_address = "https://artmagic.com.ua/static/product-placeholder.png"

        brand = ProductFilter.objects.filter(product_id=product.id, filter_category=4).first()
        brand_name = brand.filter_value.value if brand else ""        
        description = product.description if product.description else ""
        prod_quantity = "https://schema.org/InStock" if product.quantity > 0 else "https://schema.org/PreOrder"

        context = {
            'product': product,
            'description': description,
            'prod_quantity': prod_quantity,
            'attributes': attributes,
            'all_images': all_images,
            'breadcrumbs': breadcrumbs,
            'image_address': image_address,
            'brand_name': brand_name
        }

        return render(request, self.template_name, context=context)

    def build_images(self, product, images):
        all_images = []

        if product.image:
            all_images.append(product.image.url)

        for image in images:
            if image.image:
                all_images.append(image.image.url)
        return all_images
    
    def get_breadcrumbs(self, categories):
        breadcrumbs = [{'name': 'Головна', 'url': '/'}]
        if not categories:
            breadcrumbs.append({'name': '', 'url': ''})
            return breadcrumbs
        parent = categories[0].category_id.parent

        breadcrumbs.append({
            'name': parent.name,
            'url': parent.get_absolute_url()})
        print('breadcrumbs', breadcrumbs)
        for category_to_product in categories:
            category = category_to_product.category_id
            print("category", category)            
                
            if not any(b['name'] == category.name and b['url'] == f'/product/{category.slug}/' for b in breadcrumbs):
                breadcrumbs.append({
                    'name': category.name,
                    'url': f'/product/{category.slug}/'
                })
                    
        return breadcrumbs



@api_view(['POST'])
def upsert_product(request):
    # Проверка специального ключа для 1С


    onec_api_key = request.headers.get('X-1C-API-Key')
    if not onec_api_key or onec_api_key != settings.ONEC_API_KEY:
        raise PermissionDenied('Invalid 1C API key')

    sync_id = uuid.uuid4()
    started_at = timezone.now()
    success_count = 0
    error_count = 0
    try:
        # Получаем сырые данные
        byte_string = request.body
        logger.debug(f"Received raw data length: {len(byte_string)}")

        try:
            # Декодируем и очищаем данные
            raw_data = byte_string.decode('utf-8')
            
            # Очищаем JSON от проблемных символов
            raw_data = raw_data.replace('\n', '')
            raw_data = raw_data.replace('\r', '')
            raw_data = raw_data.replace('\t', '')
            raw_data = re.sub(r'\s*,\s*]', ']', raw_data)  # Убираем запятую перед закрывающей скобкой
            raw_data = re.sub(r',\s*}', '}', raw_data)     # Убираем запятую перед закрывающей фигурной скобкой
            # Проверяем, что JSON начинается и заканчивается правильно
            raw_data = raw_data.strip()
            if not raw_data.startswith('['):
                raw_data = '[' + raw_data
            if not raw_data.endswith(']'):
                raw_data = raw_data + ']'

 
            raw_data = ''.join(ch for ch in raw_data if ord(ch) >= 32)

            logger.debug(f"Cleaned data: {raw_data[:200]}...")  # Логируем первые 200 символов

            try:
                # Пробуем распарсить JSON
                data = json.loads(raw_data)
                logger.debug("JSON successfully parsed")
            except json.JSONDecodeError as e:
                # Если не получилось, пробуем исправить возможные проблемы
                logger.error(f"First JSON parse attempt failed: {str(e)}")

                # Диагностика: покажем проблемный участок (символы + коды),
                # чтобы можно было убрать их на стороне 1С.
                try:
                    pos = getattr(e, "pos", None)
                    if isinstance(pos, int):
                        window_before = 90
                        window_after = 20
                        start = max(0, pos - window_before)
                        end = min(len(raw_data), pos + window_after)
                        snippet = raw_data[start:end]
                        logger.error(f"JSON error pos={pos}, context_range=[{start}:{end}]")
                        logger.error(
                            "JSON error context (repr): " + repr(snippet)
                        )
                        logger.error(
                            "JSON error context (ord/hex): "
                            + " ".join(f"{ord(c)}({hex(ord(c))})" for c in snippet)
                        )
                except Exception as diag_err:
                    logger.error(f"Failed to build JSON error diagnostics: {diag_err}")
                
                # Попытка исправить проблемы с JSON
                raw_data = re.sub(r'}\s*{', '},{', raw_data)  # Исправляем отсутствующие запятые между объектами
                raw_data = re.sub(r'\}\s*\]', '}]', raw_data)  # Убираем пробелы перед закрывающей скобкой
                
                # Пробуем снова распарсить
                try:
                    data = json.loads(raw_data)
                    logger.debug("JSON parsed after cleanup")
                except json.JSONDecodeError as e2:
                    logger.error(f"Second JSON parse attempt failed: {str(e2)}")
                    try:
                        pos2 = getattr(e2, "pos", None)
                        if isinstance(pos2, int):
                            window_before2 = 90
                            window_after2 = 20
                            start2 = max(0, pos2 - window_before2)
                            end2 = min(len(raw_data), pos2 + window_after2)
                            snippet2 = raw_data[start2:end2]
                            logger.error(f"JSON error (2nd) pos={pos2}, context_range=[{start2}:{end2}]")
                            logger.error(
                                "JSON error (2nd) context (repr): " + repr(snippet2)
                            )
                            logger.error(
                                "JSON error (2nd) context (ord/hex): "
                                + " ".join(f"{ord(c)}({hex(ord(c))})" for c in snippet2)
                            )
                    except Exception as diag_err2:
                        logger.error(f"Failed to build 2nd JSON error diagnostics: {diag_err2}")
                    raise

        except UnicodeDecodeError as e:
            logger.error("sync_products_decode_failed sync_id=%s", sync_id)
            record_sync_run(sync_id, started_at, SyncRun.STATUS_FAILED, 0, 1, "decode")
            return Response({
                'status': 'error',
                'message': 'Unable to decode data',
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

        # Проверяем результат
        if not isinstance(data, list):
            data = [data]

        responses = []
        success_ids = []

        for product_data in data:
            model = ""
            try:
                if not isinstance(product_data, dict) or not product_data.get('model'):
                    error_count += 1
                    logger.error("sync_products_row sync_id=%s model=%s reason=model_required", sync_id, "")
                    responses.append({
                        'status': 'error',
                        'message': 'Model is required',
                        'data': product_data
                    })
                    continue
                
                model = product_data.get('model')
                name = product_data.get('name', '').strip()

                try:
                    price = Decimal(str(product_data.get('price', 0)))
                    quantity_value = Decimal(
                        str(product_data.get('quantity', 0))
                    )
                except (InvalidOperation, ValueError, TypeError) as exc:
                    raise ValueError("Invalid numeric value") from exc
                if not price.is_finite() or price < 0:
                    raise ValueError("Price must be a non-negative number")
                if (
                    not quantity_value.is_finite()
                    or quantity_value < 0
                    or quantity_value != quantity_value.to_integral_value()
                ):
                    raise ValueError(
                        "Quantity must be a non-negative integer"
                    )
                quantity = int(quantity_value)

                product, created = Products.objects.update_or_create(
                    model=model,
                    defaults={
                        'slug': slugify(unidecode(name)),
                        'name': name,
                        'price': price,
                        'quantity': quantity
                    }
                )

                success_count += 1
                success_ids.append(product.id)
                responses.append({
                    'status': 'success',
                    'message': f'Product {model} was {"created" if created else "updated"}',
                    'product_id': product.id
                })

            except Exception as e:
                error_count += 1
                logger.error("sync_products_row sync_id=%s model=%s reason=%s", sync_id, model, e)
                responses.append({
                    'status': 'error',
                    'message': 'Error processing product',
                    'error': str(e),
                    'data': product_data
                })

        if success_ids:
            try:
                reconcile_pending_reservations(success_ids, started_at)
            except Exception as exc:
                logger.exception("sync_reconcile_failed sync_id=%s", sync_id)
                error_count += 1
                responses.append({
                    'status': 'error',
                    'message': 'Reservation reconciliation failed',
                    'error': str(exc),
                })
        if error_count and success_count:
            sync_status = SyncRun.STATUS_PARTIAL
            http_status = 207
        elif error_count:
            sync_status = SyncRun.STATUS_FAILED
            http_status = status.HTTP_400_BAD_REQUEST
        else:
            sync_status = SyncRun.STATUS_SUCCESS
            http_status = status.HTTP_200_OK
        record_sync_run(sync_id, started_at, sync_status, success_count, error_count)
        logger.info(
            "sync_products sync_id=%s status=%s success=%s failed=%s",
            sync_id,
            sync_status,
            success_count,
            error_count,
        )
        return Response({
            'status': sync_status,
            'sync_id': str(sync_id),
            'summary': {
                'total': len(responses),
                'successful': success_count,
                'failed': error_count
            },
            'details': responses
        }, status=http_status)

    except json.JSONDecodeError as e:
        logger.error("sync_products_json_failed sync_id=%s", sync_id)
        record_sync_run(sync_id, started_at, SyncRun.STATUS_FAILED, success_count, error_count or 1, "json")
        # Возвращаем больше информации для отладки
        return Response({
            'status': 'error',
            'message': 'Invalid JSON format',
            'error': str(e),
            'received_data': raw_data[:500] if 'raw_data' in locals() else None,
            'error_position': {
                'line': e.lineno,
                'column': e.colno,
                'char_position': e.pos
            }
        }, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.exception("sync_products_failed sync_id=%s", sync_id)
        record_sync_run(sync_id, started_at, SyncRun.STATUS_FAILED, success_count, error_count or 1, "unexpected")
        return Response({
            'status': 'error',
            'message': 'Unexpected error during processing',
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

from django.http import HttpResponse
import xml.etree.ElementTree as ET

def generate_google_merchant_feed(request):
    
    rss = ET.Element("rss", attrib={"version": "2.0", "xmlns:g": "http://base.google.com/ns/1.0"})
    channel = ET.SubElement(rss, "channel")
    
    ET.SubElement(channel, "title").text = "Артмагія"
    ET.SubElement(channel, "link").text = "https://artmagic.com.ua"
    ET.SubElement(channel, "description").text = "Ми працюємо для вас з 2008 року і вже завоювали серця клієнтів по всій Україні. Ми найбільш цікавий продавець художніх матеріалів для всіх, хто займається творчістю. Ми можемо задовольнити всі творчі потреби художників, студентів, дизайнерів, аматорів, у нас є все для хобі. Ми надихаємо людей займатися улюбленою справою."

    products = Products.objects.filter(quantity__isnull=False, quantity__gt=0)    
    product_ids = [p.id for p in products]

    brand_filters = ProductFilter.objects.filter(filter_category_id=4).select_related('filter_value')
    brand_dict = {pf.product_id: pf.filter_value.value for pf in brand_filters}


    product_categories = ProductToCategory.objects.filter(
        product_id__in=product_ids
    ).select_related('category_id__parent')
    category_dict = {}
    for pc in product_categories:
        if pc.product_id_id not in category_dict:
            parent = pc.category_id.parent
            category_dict[pc.product_id_id] = (
                f"{parent.name} > {pc.category_id.name}" 
                if parent 
                else ''
            )

    for product in products:
        item = ET.SubElement(channel, "item")

        image = f'https://artmagic.com.ua/media/{str(product.image)}'
        no_image = f'https://artmagic.com.ua/static/product-placeholder.png'

        brand_name = brand_dict.get(product.id, "")
        result_category = category_dict.get(product.id, "")

        ET.SubElement(item, "g:id").text = str(product.id)
        ET.SubElement(item, "g:title").text = product.name
        ET.SubElement(item, "g:description").text = str(strip_tags(product.description))[:500] if product.description else ''
        ET.SubElement(item, "g:link").text = f'https://artmagic.com.ua/product/detaile-product/{product.id}/'
        ET.SubElement(item, "g:image_link").text = image if product.image else no_image
        ET.SubElement(item, "g:price").text = f'{product.price} UAH'
        ET.SubElement(item, "g:product_type").text = result_category
        ET.SubElement(item, "g:brand").text = brand_name
        ET.SubElement(item, "g:availability").text = 'in_stock'

    tree = ET.ElementTree(rss)

    response = HttpResponse(content_type='application/xml')
    tree.write(response, encoding="UTF-8", xml_declaration=True)
    return response


def tr_handler404(request, exception):
    """
    Обработка ошибки 404
    """
    return render(request=request, template_name='products/error_page.html', status=404, context={
        'title': 'Сторінку не знайдено',
        'error_message': 'Неправильно набрано адресу або такої сторінки на сайті більше не існує.',
    })


def tr_handler500(request):
    """
    Обработка ошибки 500
    """
    return render(request=request, template_name='products/error_page.html', status=500, context={
        'title': 'Помилка сервера',
        'error_message': 'На сервері сталася помилка. Спробуйте оновити сторінку або повернутися трохи пізніше.',
    })