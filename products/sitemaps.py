from django.contrib.sitemaps import Sitemap
from django.shortcuts import reverse
from .models import Category, Products

# Главная страница, контакты и о нас
class StaticViewSitemap(Sitemap):
    priority = 1.0
    changefreq = 'weekly'
    protocol = "https"

    def items(self):
        return [
            'parent_categories',
            'main:about_detail',
            'main:contacts_detail',
            'main:payment_delivery_detail',
        ] 

    def location(self, item):
        return reverse(item)
    

# Список категорий
class CategorySitemap(Sitemap):
    priority = 0.8
    changefreq = 'daily'
    protocol = "https"

    def items(self):
        return Category.objects.filter(parent=None, is_active=True)

    def lastmod(self, obj):
        return obj.date_modified  
    
# Список подкатегорий
class SubCategorySitemap(Sitemap):
    priority = 0.8
    changefreq = 'daily'
    protocol = "https"

    def items(self):
        return Category.objects.filter(is_active=True).exclude(parent=None)

    def lastmod(self, obj):
        return obj.date_modified  
    
    def location(self, item):
        return reverse('sub_product', args=[item.slug])

# Список продуктов
class ProductSitemap(Sitemap):
    priority = 0.6
    changefreq = 'daily'
    protocol = "https"

    def items(self):
        return Products.objects.filter(status=True).order_by('id') 

    def lastmod(self, obj):
        return obj.date_modified 
