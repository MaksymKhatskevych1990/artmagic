"""
URL configuration for artmagic project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from pathlib import Path

from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, include
from django.conf.urls.static import static

from artmagic import settings


def google_site_verification(request):
    verification_file = Path(settings.BASE_DIR) / "googlefe45e590a621af8a.html"
    return HttpResponse(
        verification_file.read_text(encoding="utf-8"),
        content_type="text/html; charset=utf-8",
    )


urlpatterns = [
    path("googlefe45e590a621af8a.html", google_site_verification),
    path('art-admin/', admin.site.urls),
    path('', include('products.urls')),
    path('user/', include('users.urls')),
    path('cart/', include('carts.urls')),
    path('delivery/', include('delivery.urls')),
    path('payment/', include('liqpay_app.urls')),
    path('main/', include('main.urls')),
    path("ckeditor5/", include('django_ckeditor_5.urls')),
]

handler404 = 'products.views.tr_handler404'
handler500 = 'products.views.tr_handler500'

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
