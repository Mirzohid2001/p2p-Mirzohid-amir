"""Новая админ-панель с аналитикой."""
from django.core.paginator import Paginator
from django.http import Http404
from django.contrib import messages
from django.shortcuts import render, redirect
from django.urls import reverse

from users.models import User
from . import analytics
from .views import admin_required

# Только участники этой группы видят и меняют «Настройки игры» (пауза между партиями)
CONTROL_GROUP = "Контроль игры"


def can_control_game(user):
    return bool(user.is_authenticated and user.is_superuser and user.groups.filter(name=CONTROL_GROUP).exists())


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
    ctx = {"tab": tab, "tabs": TABS, "can_control": can_control_game(request.user)}

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


@admin_required
def game_settings_save(request):
    """Пауза между партиями: включить/выключить и сколько секунд."""
    from rps.models import GameSettings
    if not can_control_game(request.user):
        messages.error(request, "Недостаточно прав")
        return redirect(reverse("admin_dashboard") + "?tab=games")
    if request.method == "POST":
        gs = GameSettings.get()
        gs.cooldown_enabled = request.POST.get("cooldown_enabled") == "on"
        try:
            seconds = int(request.POST.get("cooldown_seconds", gs.cooldown_seconds))
        except (TypeError, ValueError):
            seconds = gs.cooldown_seconds
        gs.cooldown_seconds = max(1, min(seconds, 120))
        gs.save()
        state = f"включена, {gs.cooldown_seconds} с" if gs.cooldown_enabled else "выключена"
        messages.success(request, f"Пауза между партиями {state}")
    return redirect(reverse("admin_dashboard") + "?tab=games")


@admin_required
def antibot_unban(request, telegram_id):
    """Снять блокировку КНБ, наложенную антиботом."""
    from rps.models import PlayerGuard
    from rps.antibot import unban
    if request.method == "POST":
        guard = PlayerGuard.objects.filter(user_id=telegram_id).first()
        if guard:
            unban(guard)
            messages.success(request, f"Игрок {telegram_id} разблокирован в КНБ")
    return redirect(reverse("admin_dashboard") + "?tab=games")


@admin_required
def tournament_requalify(request, participant_id):
    """Вернуть игрока в турнир после снятия (если блокировка была ошибкой)."""
    from rps.models import TournamentParticipant
    if request.method == "POST":
        p = TournamentParticipant.objects.filter(pk=participant_id).first()
        if p:
            p.disqualified = False
            p.disqualified_reason = ""
            p.disqualified_at = None
            p.save(update_fields=["disqualified", "disqualified_reason", "disqualified_at"])
            messages.success(request, f"{p.user} возвращён в турнир #{p.tournament_id} с {p.points} очками")
    return redirect(reverse("admin_dashboard") + "?tab=games")


@admin_required
def bot_pool_topup(request):
    """Пополнить пул бота (из него бот ставит свою ставку в игре)."""
    from decimal import Decimal, InvalidOperation
    from django.db.models import F
    from rps.models import BotPool
    if request.method == "POST":
        try:
            amount = Decimal(str(request.POST.get("amount", "")).replace(",", "."))
        except (InvalidOperation, ValueError):
            amount = Decimal(0)
        if amount <= 0 or amount > 1_000_000:
            messages.error(request, "Сумма должна быть от 1 до 1 000 000 FL")
        else:
            pool = BotPool.get_pool()
            BotPool.objects.filter(pk=pool.pk).update(total_balance=F("total_balance") + amount)
            pool.refresh_from_db()
            left = pool.total_balance - pool.used_balance
            messages.success(request, f"Пул бота пополнен на {amount:.0f} FL — теперь в нём {left:.0f} FL")
    return redirect(reverse("admin_dashboard") + "?tab=economy")
