from django.urls import path
from . import views

app_name = "p2p"

urlpatterns = [
    path('', views.p2p_market, name='market'),
    path('buy-ajax/', views.buy_ajax, name='buy_ajax'),
    path('sell-order/', views.create_order_sell, name='sell_order'),
path('buy_order/', views.buy_order, name='buy_order'),
path('price-history-json/', views.price_history_json, name='price_history_json'),
]
