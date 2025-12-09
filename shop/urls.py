from django.urls import path
from . import views
from .views import buy_ton_tree

app_name = 'shop'

urlpatterns = [
    path('', views.shop, name='shop'),
    path('buy/auto_water/', views.buy_auto_water, name='buy_auto_water'),
    path('buy/<int:item_id>/', views.buy_shop_item, name='buy_shop_item'),
    path('use/<int:purchase_id>/', views.use_shop_item, name='use_shop_item'),
    path('buy/branches/', views.buy_branches, name='buy_branches'),
    path('buy_fertilizer/', views.buy_fertilizer, name='buy_fertilizer'),
    path("buy_ton_tree/", views.buy_ton_tree, name="buy_ton_tree"),
]