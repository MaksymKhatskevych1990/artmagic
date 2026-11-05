from django.urls import path
from carts.views import CheckoutView, ProcessOrderView, RefreshCartView
from carts import views

app_name = 'carts'

urlpatterns = [
    path('refresh/', RefreshCartView.as_view(), name='refresh_cart'),
    path('checkout/', CheckoutView.as_view(), name='checkout'),
    path('process-order/', ProcessOrderView.as_view(), name='process_order'),
]