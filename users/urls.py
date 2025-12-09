from django.urls import path
from . import views
from .views import save_wallet

urlpatterns = [
    path("", views.telegram_login, name="telegram_login"),
    path('profile/', views.profile_view, name='profile'),
    path('deposit_ton/', views.deposit_ton, name='deposit_ton'),
path('save_wallet/', save_wallet, name='save_wallet'),

] 