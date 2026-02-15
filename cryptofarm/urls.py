"""
URL configuration for cryptofarm project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
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
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from users.views import save_wallet, get_ton_balance
from django.views.i18n import JavaScriptCatalog

urlpatterns = [
    path('admin/', admin.site.urls),
path('save_wallet/', save_wallet, name='save_wallet'),
    path('', include('trees.urls')),  # Главная страница с деревьями
    path('shop/', include('shop.urls')),
    path('p2p/', include('p2p.urls')),
    path('referral/', include('referrals.urls')),
    path('staking/', include('staking.urls')),
    path('telegram_login/', include("users.urls")),
    path('admin-panel/', include('admin_panel.urls')),  # Наша новая админ-панель
    path('rps/', include('rps.urls')),  # Камень-Ножницы-Бумага
    path('get_ton_balance/', get_ton_balance, name='get_ton_balance'),
    path("i18n/", include("django.conf.urls.i18n")),   # set_language
    path("jsi18n/", JavaScriptCatalog.as_view(), name="javascript-catalog"),


]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
