from django.db import models
from django.urls import reverse
from django.utils.text import slugify

from django_ckeditor_5.fields import CKEditor5Field
from mptt.models import MPTTModel, TreeForeignKey
from unidecode import unidecode 


class Category(MPTTModel):
    name = models.CharField(
        max_length=295, 
        unique=True, 
        verbose_name='Назва'
    )
    description = models.TextField(
        null=True, 
        blank=True, 
        verbose_name='Опис'
    )
    meta_title = models.CharField(
        max_length=255, 
        null=True, 
        blank=True,
        verbose_name='Meta Title'
    )
    meta_description = models.TextField(
        max_length=255, 
        null=True, 
        blank=True, 
        verbose_name='Meta Description'
    )
    meta_keyword = models.CharField(
        max_length=255, 
        blank=True, 
        null=True, 
        verbose_name='Meta Keywords'
    )
    seo_keyword = models.CharField(
        max_length=255, 
        blank=True, 
        null=True, 
        verbose_name='SEO Keywords'
    )
    image = models.ImageField(
        upload_to='catalog/', 
        null=True, 
        blank=True, 
        max_length=300, 
        verbose_name='Зображення'
    )
    parent = TreeForeignKey(
        'self', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='children', 
        verbose_name='Батьківська категорія'
    )
    date_added = models.DateTimeField(
        auto_now_add=True, 
        verbose_name='Дата додавання'
    )
    date_modified = models.DateTimeField(
        auto_now=True, 
        verbose_name='Дата зміни'
    )
    slug = models.SlugField(
        max_length=299, 
        blank=True, 
        null=True, 
        verbose_name='Slug'
    )
    lft = models.PositiveIntegerField(
        editable=False, 
        db_index=True, 
        null=True, 
        verbose_name='Ліва межа'
    )
    rght = models.PositiveIntegerField(
        editable=False, 
        db_index=True, 
        null=True, 
        verbose_name='Права межа'
    )
    tree_id = models.PositiveIntegerField(
        editable=False, 
        db_index=True, 
        null=True, 
        verbose_name='ID дерева'
    )
    level = models.PositiveIntegerField(
        editable=False, 
        null=True, 
        verbose_name='Рівень'
    )
    is_active = models.BooleanField(
        default=True, 
        verbose_name='Активний'
    )

    class MPTTMeta:
        order_insertion_by = ['name']

    class Meta:
        verbose_name = 'Категорія'
        verbose_name_plural = 'Категорії'

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('sub_categories', kwargs={'slug': self.slug})
    
    def save(self, *args, **kwargs):
        if not self.slug or self.slug != slugify(unidecode(self.name)):
            self.slug = slugify(unidecode(self.name))
        super().save(*args, **kwargs)


class Stocks(models.Model):
    image = models.ImageField(upload_to='stocks/', null=True, max_length=300, blank=True)
    title = models.CharField(max_length=100, verbose_name='Титул')
    description = models.TextField(verbose_name='Опис')

    def __str__(self):
        return self.title
    
    class Meta:
        verbose_name = "Акційна пропозиція"
        verbose_name_plural = "Акційні пропозиції"

class Manufacturer(models.Model):
    name = models.CharField(max_length=255, verbose_name="Назва виробника")
    image = models.ImageField(upload_to='catalog/', null=True, max_length=300, verbose_name="Зображення виробника")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Виробник"
        verbose_name_plural = "Виробники"


class FilterGroup(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Група категорій фільтрів")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Група категорій фільтрів"
        verbose_name_plural = "Групи категорій фільтрів"

class FilterCategory(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Категорія фільтрів")
    group = models.ForeignKey(FilterGroup, on_delete=models.CASCADE, null=True, related_name="categories", verbose_name="Група категорій фільтрів")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Категорію фільтрів"
        verbose_name_plural = "Категорії фільтрів"


class FilterValue(models.Model):
    category = models.ForeignKey(FilterCategory, on_delete=models.CASCADE, related_name="values", verbose_name="Категорія фільтра")
    value = models.CharField(max_length=100, verbose_name="Значення фільтра")

    def __str__(self):
        return self.value

    class Meta:
        verbose_name = "Значення фільтра"
        verbose_name_plural = "Значення фільтрів"
 

class Products(models.Model):
    name = models.CharField(
        max_length=299,
        verbose_name='Назва'
    )
    description = CKEditor5Field(
        null=True, 
        blank=True, 
        verbose_name='Опис',
        config_name='extends'
    )
    model = models.CharField(
        max_length=255, 
        blank=True, 
        unique=True, 
        verbose_name='Артикуль'
    )
    quantity = models.IntegerField(
        null=True, 
        blank=True, 
        verbose_name='Кількість'
    )
    image = models.ImageField(
        upload_to='catalog/', 
        null=True, 
        max_length=300, 
        blank=True, 
        verbose_name='Зображення'
    )
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        blank=True, 
        verbose_name='Ціна'
    )
    manufacturer = models.ForeignKey(
        Manufacturer, 
        null=True, 
        on_delete=models.CASCADE, 
        max_length=300, 
        verbose_name='Виробник'
    )
    status = models.BooleanField(
        verbose_name='Статус',
        null=True
    )
    date_added = models.DateTimeField(
        auto_now_add=True, 
        verbose_name='Дата додавання'
    )
    date_modified = models.DateTimeField(
        auto_now=True, 
        verbose_name='Дата зміни'
    )
    slug = models.SlugField(
        max_length=299, 
        blank=True, 
        null=True, 
        verbose_name='Slug'
    )
    discount = models.DecimalField(
        default=0.00, 
        max_digits=4, 
        null=True, 
        blank=True, 
        decimal_places=2, 
        verbose_name='Знижка в %'
    )


    class Meta:
        verbose_name = 'Продукт'
        verbose_name_plural = 'Продукти'

    def __str__(self):
        return self.name
    
    def get_absolute_url(self):
        return reverse('detaile_product', kwargs={'id': self.id})
    
    def save(self, *args, **kwargs):
        if not self.slug or self.slug != slugify(unidecode(self.name)):
            self.slug = slugify(unidecode(self.name))
        super().save(*args, **kwargs)


class ProductToCategory(models.Model):
    product_id = models.ForeignKey('Products', on_delete=models.CASCADE, verbose_name="Продукт")
    category_id = models.ForeignKey('Category', on_delete=models.CASCADE, verbose_name="Категорія")

    def __str__(self):
        return f"{self.category_id.name}"

    class Meta:
        verbose_name = "Категорія"
        verbose_name_plural = "Категорії"


class ProductFilter(models.Model):
    product = models.ForeignKey('Products', on_delete=models.CASCADE, related_name="filters", verbose_name="Продукт")
    filter_category = models.ForeignKey(FilterCategory, on_delete=models.CASCADE, verbose_name="Категорія фільтра")
    filter_value = models.ForeignKey(FilterValue, on_delete=models.CASCADE, verbose_name="Значення фільтра")

    def __str__(self):
        return f"{self.filter_category.name}: {self.filter_value.value}"

    class Meta:
        verbose_name = "Фільтр продукту"
        verbose_name_plural = "Фільтри продукту"


class SyncRun(models.Model):
    STATUS_SUCCESS = "success"
    STATUS_PARTIAL = "completed_with_errors"
    STATUS_FAILED = "failed"

    sync_id = models.UUIDField(unique=True)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    success_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=32, default=STATUS_FAILED)
    message = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Синхронізація 1С"
        verbose_name_plural = "Синхронізації 1С"
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.sync_id} {self.status} {self.success_count}/{self.error_count}"


class ProductImage(models.Model):
    product = models.ForeignKey('Products', on_delete=models.CASCADE, verbose_name="Продукт")
    image = models.ImageField(upload_to='catalog/', null=True, max_length=300, blank=True, verbose_name="Зображення продукту")

    def __str__(self):
        return f"{self.image}"

    class Meta:
        verbose_name = "Зображення продукту"
        verbose_name_plural = "Зображення продуктів"