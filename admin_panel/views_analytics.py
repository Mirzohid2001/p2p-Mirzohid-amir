"""Новая админ-панель с аналитикой."""
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import render

from users.models import User
from . import analytics
from .views import admin_required

TABS = [
    ("overview", "Обзор"),
    ("users", "Пользователи"),
    ("games", "Игры и турниры"),
    ("economy", "Экономика"),
    ("referrals", "Рефералы"),
]


@admin_required
def dashboard(request):
    tab = request.GET.get("tab", "overview")
    if tab not in dict(TABS):
        tab = "overview"
    ctx = {"tab": tab, "tabs": TABS}

    if tab == "overview":
        ctx.update(analytics.overview())
    elif tab == "users":
        q = request.GET.get("q", "")
        sort = request.GET.get("sort", "new")
        page = Paginator(analytics.users_list(q, sort), 50).get_page(request.GET.get("page"))
        ctx.update({"q": q, "sort": sort, "page": page, "sorts": [
            ("new", "Сначала новые"), ("old", "Сначала старые"), ("cf", "Баланс FL"),
            ("ton", "Баланс TON"), ("refs", "Рефералы"), ("games", "Игры"),
        ]})
    elif tab == "games":
        ctx.update(analytics.games())
    elif tab == "economy":
        ctx.update(analytics.economy())
    elif tab == "referrals":
        ctx.update(analytics.referrals())

    return render(request, "admin_panel/dashboard.html", ctx)


@admin_required
def user_page(request, telegram_id):
    try:
        ctx = analytics.user_detail(telegram_id)
    except User.DoesNotExist:
        raise Http404("Пользователь не найден")
    ctx.update({"tab": "users", "tabs": TABS})
    return render(request, "admin_panel/user_detail.html", ctx)
