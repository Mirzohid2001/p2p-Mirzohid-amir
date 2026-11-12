from django.urls import path
from . import views, views_analytics

urlpatterns = [
    path('', views.admin_login, name='admin_login'),  # Входная страница
    path('dashboard/', views_analytics.dashboard, name='admin_dashboard'),
    path('user/<int:telegram_id>/', views_analytics.user_page, name='admin_user'),
    path('old/', views.admin_panel, name='admin_panel_old'),  # Панель управления
    path('logout/', views.admin_logout, name='admin_logout'),  # Выход
    path('burn-tokens/', views.burn_tokens, name='burn_tokens'),
    path('create-ton-distribution/', views.create_ton_distribution, name='create_ton_distribution'),
    path('api/token-stats/', views.get_token_stats, name='get_token_stats'),
    path('user-info/', views.show_user_info, name='user_info'),  # Для отладки
]
