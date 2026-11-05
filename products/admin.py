from django.contrib import admin
from mptt.admin import MPTTModelAdmin
from django.utils.safestring import mark_safe

from .models import Products, Category, ProductFilter, FilterCategory, FilterValue, Manufacturer, ProductImage, ProductToCategory, FilterGroup, Stocks, SyncRun
from .sync import is_sync_stale
from .forms import ProductFilterForm, ProductToCategoryForm, CategoryAdminForm


class HiddenModelAdmin(admin.ModelAdmin):
    def get_model_perms(self, request):
        return {}
    

class CategoryFilter(admin.SimpleListFilter):
    template = 'admin/filters/filter.html'
    title = 'категорією'
    parameter_name = 'category'

    def lookups(self, request, model_admin):
        # Получение всех категорий, замените на вашу логику
        categories = Category.objects.all()
        return [(cat.id, cat.name) for cat in categories]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(producttocategory__category_id=self.value())
    
    def choices(self, changelist):
        choices = [
                {
                    'Всі': [
                        {'selected': True, 'query_string': '?', 'display': 'Всі'}
                    ],                    
                }
            ]
        category_choices = self.lookups(None, changelist.model_admin)
        category_ids = [k for k, v in category_choices]

        categories = Category.objects.filter(pk__in=category_ids).select_related('parent')

        for category in categories:
            temp_dict = {}
            parent_category = category.parent 
            if parent_category:
                for item in choices:
                    if parent_category.name in item:
                        item[parent_category.name].append({
                            'selected': False, 
                            'query_string': f'?category={category.pk}', 
                            'display': category.name
                            })
            else:
                temp_dict.setdefault(category.name, [])
                choices.append(temp_dict)
        return choices

class ParentCategoryFilter(admin.SimpleListFilter):
    title = 'батьківською категорією'
    parameter_name = 'category'

    def lookups(self, request, model_admin):
        # Получение всех категорий, замените на вашу логику
        categories = Category.objects.filter(parent=None)
        return [(cat.id, cat.name) for cat in categories]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(parent__id=self.value())
        return queryset

@admin.register(Category)
class CategoryAdmin(MPTTModelAdmin):
    form = CategoryAdminForm 

    list_display = ('name', 'parent', 'is_active', 'date_added', 'date_modified')
    list_filter = ('is_active', ParentCategoryFilter)
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}
    ordering = ('tree_id', 'lft')
    mptt_level_indent = 20
    list_editable = ('is_active',)
    readonly_fields = ('date_added', 'date_modified')
    extra = 1
    # ordering = ('name',)

    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'parent', 'description', 'image')
        }),
        ('SEO Settings', {
            'classes': ('collapse',),
            'fields': ('meta_title', 'meta_description', 'meta_keyword', 'seo_keyword')
        }),
        ('Status and Dates', {
            'fields': ('is_active', 'date_added', 'date_modified')
        }),
    )

class ProductFilterInline(admin.TabularInline):
    form = ProductFilterForm
    model = ProductFilter
    verbose_name = "Фільтр продукта"
    verbose_name_plural = "Фільтра продуктів"
    extra = 1

    class Media:
        js = ('js/filter_dynamic.js',)  # Подключаем файл с вашим JS

class ProductImageInline(admin.TabularInline):
    model = ProductImage
    verbose_name = "Зображення"
    verbose_name_plural = "Додаткові Зображення продукту"
    extra = 1

class ProductToCategoryInline(admin.TabularInline):
    model = ProductToCategory
    form = ProductToCategoryForm
    verbose_name = "Категорія"
    verbose_name_plural = "Додати категорію"
    extra = 2

    class Media:
            js = ('js/filter_dynamic.js',)  # Подключаем файл с вашим JS
            
@admin.register(Products)
class ProductsAdmin(admin.ModelAdmin):
    inlines = [ProductToCategoryInline, ProductFilterInline, ProductImageInline]
    
    list_display = ('name', 'model', 'get_categories', 'manufacturer', 'price', 'quantity')
    search_fields = ('name', 'model', 'manufacturer__name')
    list_filter = (CategoryFilter,)  # Используем кастомный фильтр
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ('price', 'quantity')
    readonly_fields = ('date_added', 'date_modified')
    ordering = ('-date_added',)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "manufacturer":  # Замените на фактическое имя поля
            kwargs["queryset"] = db_field.related_model.objects.order_by("name")  # Сортировка по имени
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
    
    def get_categories(self, obj):
        categories = [category.category_id.name for category in obj.producttocategory_set.all()]
        return mark_safe("<br>".join(categories))
    get_categories.short_description = 'Категорії'

    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'description', 'model', 'image', 'manufacturer')
        }),
        ('Наявність та ціни', {
            'fields': ('price', 'discount', 'quantity')
        }),
        ('Статус', {
            'fields': ('status', )
        }),
    )


@admin.register(FilterGroup)
class FilterGroupAdmin(admin.ModelAdmin):
    ordering = ('name',)
    
@admin.register(FilterCategory)
class FilterCategoryAdmin(admin.ModelAdmin):
    list_filter = ('group__name',)
    ordering = ('name',)

@admin.register(FilterValue)
class FilterValueAdmin(admin.ModelAdmin):
    search_fields = ('value',)
    list_filter = ('category',)
    extra = 1
    ordering = ('value',)
    



admin.site.register(Manufacturer, HiddenModelAdmin)
admin.site.register(Stocks)
admin.site.register(ProductFilter, HiddenModelAdmin)


@admin.register(SyncRun)
class SyncRunAdmin(admin.ModelAdmin):
    change_list_template = "admin/products/syncrun/change_list.html"
    list_display = ("started_at", "finished_at", "status", "success_count", "error_count", "sync_id")
    readonly_fields = ("sync_id", "started_at", "finished_at", "status", "success_count", "error_count", "message")

    def has_add_permission(self, request):
        return False

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        last = SyncRun.objects.filter(status=SyncRun.STATUS_SUCCESS).order_by("-finished_at").first()
        extra_context["last_success"] = last.finished_at if last else None
        extra_context["sync_stale"] = is_sync_stale()
        return super().changelist_view(request, extra_context=extra_context)