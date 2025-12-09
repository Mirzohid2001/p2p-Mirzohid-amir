from django.urls import path, include
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Главная страница
    path('', views.home, name='home'),
    
    # Авторизация
    path('login/', auth_views.LoginView.as_view(template_name='farm/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('telegram-auth/', views.telegram_auth, name='telegram_auth'),
    
    # Деревья
    path('tree/<int:tree_id>/', views.tree_detail, name='tree_detail'),
    path('tree/<int:tree_id>/water/', views.water_tree_view, name='water_tree'),
    path('tree/<int:tree_id>/auto-water/', views.auto_water_tree_view, name='auto_water_tree'),
    path('tree/<int:tree_id>/fertilize/', views.fertilize_tree_view, name='fertilize_tree'),
    path('tree/<int:tree_id>/upgrade/', views.upgrade_tree_view, name='upgrade_tree'),
    path('create-tree/', views.create_tree, name='create_tree'),
    
    # Рынок
    path('market/', views.market, name='market'),
    path('market/create-order/', views.create_order, name='create_order'),
    path('market/buy/<int:order_id>/', views.buy_order, name='buy_order'),
    path('market/cancel/<int:order_id>/', views.cancel_order, name='cancel_order'),
    
    # P2P
    path('p2p/', views.p2p_market, name='p2p_market'),
    path('p2p/my-orders/', views.my_p2p_orders, name='my_p2p_orders'),
    path('p2p/create/', views.create_p2p_order, name='create_p2p_order'),
    path('p2p/buy/<int:order_id>/', views.buy_p2p_order, name='buy_p2p_order'),
    path('p2p/cancel/<int:order_id>/', views.cancel_p2p_order, name='cancel_p2p_order'),
    
    # Специальные деревья
    path('special-trees/', views.special_trees, name='special_trees'),
    path('special-trees/buy/<str:kind>/', views.buy_special_tree_view, name='buy_special_tree'),
    
    # Staking
    path('staking/', views.staking_list, name='staking_list'),
    path('staking/create/', views.create_staking_view, name='create_staking'),
    
    # Donations
    path('donations/', views.donations, name='donations'),
    path('donations/make/', views.make_donation, name='make_donation'),
    
    # Ads
    path('ads/', views.ads_market, name='ads_market'),
    path('ads/buy/<int:slot_id>/', views.buy_ad_slot, name='buy_ad_slot'),
    
    # Tree Purchases
    path('tree-purchases/', views.tree_purchases, name='tree_purchases'),
    path('tree-purchases/confirm/', views.confirm_tree_purchase, name='confirm_tree_purchase'),
    
    # Профиль и статистика
    path('profile/', views.profile, name='profile'),
    path('transactions/', views.transactions, name='transactions'),
    path('referrals/', views.referrals, name='referrals'),
    path('stats/', views.detailed_stats, name='detailed_stats'),
    
    # Logs
    path('water-logs/', views.water_logs, name='water_logs'),
    path('water-logs/<int:tree_id>/', views.water_logs, name='tree_water_logs'),
    path('upgrade-logs/', views.upgrade_logs, name='upgrade_logs'),
    path('upgrade-logs/<int:tree_id>/', views.upgrade_logs, name='tree_upgrade_logs'),
    
    # Tree Types
    path('tree-types/', views.tree_types, name='tree_types'),
    
    # Staking Detail
    path('staking/<int:staking_id>/', views.staking_detail, name='staking_detail'),
    
    # Админ
    path('admin-analytics/', views.admin_analytics, name='admin_analytics'),
    path('admin/telegram-users/', views.telegram_users, name='admin_telegram_users'),
    path('admin/all-orders/', views.all_orders, name='admin_all_orders'),
    path('admin/all-p2p-orders/', views.all_p2p_orders, name='admin_all_p2p_orders'),
    path('admin/all-transactions/', views.all_transactions, name='admin_all_transactions'),
]
