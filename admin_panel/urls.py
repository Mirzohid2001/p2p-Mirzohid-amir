from django.urls import path
from . import views

urlpatterns = [
    path('', views.admin_login, name='admin_login'),  # Входная страница
    path('dashboard/', views.admin_panel, name='admin_dashboard'),  # Панель управления
    path('logout/', views.admin_logout, name='admin_logout'),  # Выход
    path('burn-tokens/', views.burn_tokens, name='burn_tokens'),
    path('create-ton-distribution/', views.create_ton_distribution, name='create_ton_distribution'),
    path('api/token-stats/', views.get_token_stats, name='get_token_stats'),
    path('user-info/', views.show_user_info, name='user_info'),  # Для отладки
]
