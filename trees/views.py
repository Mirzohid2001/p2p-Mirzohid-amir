# trees/views.py
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from shop.models import ShopItem, Purchase
from .models import Tree, TonDistribution, BurnedToken
from users.models import User as TelegramUser, User
from .utils import apply_item_to_tree, use_purchase_for_cf_tree


# Если у вас в проекте есть модель для логов, раскомментируйте импорт и используйте её.
# from .models import TreeLog


def get_current_user(request):
    """
    Возвращает текущего залогиненного TelegramUser по session['telegram_id'].
    """
    tg_id = request.session.get("telegram_id")
    if not tg_id:
        return None
    try:
        return TelegramUser.objects.get(telegram_id=tg_id)
    except TelegramUser.DoesNotExist:
        return None


def home(request):
    user = get_current_user(request)
    TOTAL_CREATED_CF = 25000000
    all_cf_grown = User.objects.aggregate(total=Sum('cf_balance'))['total'] or 0
    burned = BurnedToken.objects.aggregate(total=Sum('amount'))['total'] or 0

    cf_left = TOTAL_CREATED_CF - all_cf_grown - burned

    if not user:
        return render(request, "not_authenticated.html")

    cf_trees = Tree.objects.filter(user=user, type="CF")
    if not cf_trees.exists():
        Tree.objects.create(user=user, type="CF")
        cf_trees = Tree.objects.filter(user=user, type="CF")

    ton_trees = Tree.objects.filter(user=user, type="TON")

    active_distribution = TonDistribution.objects.filter(is_active=True).last()
    participants_count = (
        TelegramUser.objects.filter(trees__type="TON").distinct().count()
    ) or 0

    ton_per_water = None
    ton_left = None
    if active_distribution and participants_count > 0:
        ton_per_water = 1  # или tree.level если их несколько, здесь просто для вывода на главной
        ton_left = active_distribution.left_to_distribute

    cf_tree_infos = []
    for tree in cf_trees:
        cf_tree_infos.append({
            "id": tree.id,
            "level": tree.level,
            "income_per_hour": float(tree.income_per_hour),
            "branches_collected": tree.branches_collected,
            "last_watered": tree.last_watered,
            "water_percent": tree.get_water_percent(),
            "pending_income": float(tree.get_pending_income()),
            "is_watered": tree.is_watered(),
            "is_fertilized": bool(tree.fertilized_until and tree.fertilized_until > timezone.now()),
            "is_auto_watered": bool(tree.auto_water_until and tree.auto_water_until > timezone.now()),
        })

    ton_tree_infos = []
    for tree in ton_trees:
        is_fertilized = bool(tree.fertilized_until and tree.fertilized_until > timezone.now())

        base_per_hour = Decimal(tree.level) * Decimal("0.01")  # 0.01..0.05 TON/час
        ton_per_hour = base_per_hour * (Decimal("2") if is_fertilized else Decimal("1"))

        ton_tree_infos.append({
            "id": tree.id,
            "level": tree.level,
            "pending_income": float(tree.get_pending_income()),
            "is_fertilized": is_fertilized,
            "is_auto_watered": bool(tree.auto_water_until and tree.auto_water_until > timezone.now()),
            "ton_per_hour": float(ton_per_hour),  # ✅ показываем TON/час
        })

    return render(request, "home.html", {
        "user": user,
        "cf_trees": cf_tree_infos,
        "ton_trees": ton_tree_infos,
        "active_distribution": active_distribution,
        "participants_count": participants_count,
        "ton_per_water": ton_per_water,
        "ton_left": ton_left,
        "total_created_cf": TOTAL_CREATED_CF,
        "all_cf_grown": all_cf_grown,
        "cf_left": cf_left,
        "burned": burned,
    })



def tree_detail(request, tree_id):
    user = get_current_user(request)
    now = timezone.now()
    if not user:
        return render(request, "not_authenticated.html")

    tree = get_object_or_404(Tree, id=tree_id, user=user)

    is_watered = tree.is_watered()
    is_fertilized = bool(tree.fertilized_until and tree.fertilized_until > now)
    is_auto_watered = bool(tree.auto_water_until and tree.auto_water_until > now)
    can_upgrade = tree.can_upgrade()
    TOTAL_CREATED_CF = 25_000_000
    all_cf_grown = User.objects.aggregate(total=Sum('cf_balance'))['total'] or 0
    cf_left = TOTAL_CREATED_CF - all_cf_grown
    last_watered = tree.last_watered
    water_cooldown = timedelta(hours=5)
    fertilizer_time_left = int((tree.fertilized_until - now).total_seconds()) if is_fertilized else 0
    auto_water_time_left = int((tree.auto_water_until - now).total_seconds()) if is_auto_watered else 0
    income_per_hour = float(tree.income_per_hour)
    income_bonus = income_per_hour if is_fertilized else 0
    total_income = income_per_hour + income_bonus

    user_cf_grown = user.cf_balance if user else 0
    auto_water_active = bool(tree.auto_water_until and tree.auto_water_until > now)
    fertilizer_active = bool(tree.fertilized_until and tree.fertilized_until > now)
    pending_income = float(tree.get_pending_income())

    autowater_purchases = Purchase.objects.filter(
        user=user,
        item__type='auto_water'
    )
    fertilizer_purchases = Purchase.objects.filter(
        user=user,
        item__type='fertilizer'
    )

    if last_watered:
        next_water = last_watered + water_cooldown
        time_left = (next_water - now).total_seconds()
        can_water = time_left <= 0
    else:
        time_left = 0
        can_water = True

    context = {
        "user": user,
        "tree": tree,
        "is_watered": is_watered,
        "is_fertilized": is_fertilized,
        "is_auto_watered": is_auto_watered,
        "fertilizer_time_left": fertilizer_time_left,
        "auto_water_time_left": auto_water_time_left,
        "can_upgrade": can_upgrade,
        "water_percent": tree.get_water_percent(),
        "pending_income": pending_income,
        'total_created_cf': TOTAL_CREATED_CF,
        "cf_left": cf_left,
        'all_cf_grown': all_cf_grown,
        "user_cf_grown": user_cf_grown,
        'now': now,
        'auto_water_active': auto_water_active,
        'fertilizer_active': fertilizer_active,
        "income_per_hour": income_per_hour,
        "income_bonus": income_bonus,
        "total_income": total_income,
        "time_left": max(0, int(time_left)),
        "can_water": can_water,
        "last_watered": last_watered,
        "autowater_purchases": autowater_purchases,
        "user_has_autowater_item": bool(autowater_purchases),
        "fertilizer_purchases": fertilizer_purchases,
        "user_has_fertilizer_item": bool(fertilizer_purchases),
        "can_collect": pending_income > 0,
        "branches_balance": user.branches_balance,
    }

    # Специфично для TON дерева — добавляем TON данные
    if tree.type == "TON":
        active_dist = TonDistribution.objects.filter(is_active=True).last()
        participants_count = TelegramUser.objects.filter(trees__type="TON").distinct().count() or 0

        is_fertilized = bool(tree.fertilized_until and tree.fertilized_until > now)

        base_per_hour = Decimal(tree.level) * Decimal("0.01")
        ton_per_hour = base_per_hour * (Decimal("2") if is_fertilized else Decimal("1"))

        ton_left = active_dist.left_to_distribute if active_dist else Decimal("0")

        context.update({
            "active_distribution": active_dist,
            "participants_count": participants_count,
            "ton_per_hour": ton_per_hour,  # ✅ правильно
            "ton_per_hour_base": base_per_hour,  # ✅ правильно
            "ton_left": ton_left,
            "is_fertilized": is_fertilized,
        })

    return render(request, "tree/detail.html", context)





from django.utils.timezone import localtime

def water_tree(request, tree_id):
    user = get_current_user(request)
    if not user:
        return JsonResponse({"status": "error", "message": "Сначала авторизуйтесь"}, status=403)

    tree = get_object_or_404(Tree, id=tree_id, user=user)

    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Требуется метод POST"}, status=400)

    # ✅ ВАЖНО: TON дерево можно поливать только при активной раздаче
    if tree.type == "TON":
        active_dist = TonDistribution.objects.filter(is_active=True).last()
        if not active_dist:
            return JsonResponse({
                "status": "error",
                "message": "⛔ Раздача TON сейчас не активна. Полив TON-дерева доступен только во время акции."
            }, status=400)

        # (опционально) если раздача уже закончилась по факту
        if hasattr(active_dist, "left_to_distribute") and active_dist.left_to_distribute <= 0:
            return JsonResponse({
                "status": "error",
                "message": "⛔ Раздача TON завершена. Дождитесь следующей акции."
            }, status=400)

    result = tree.water()
    if not result.get("ok", True):
        return JsonResponse({
            "status": "error",
            "message": result.get("message", "Нельзя полить сейчас"),
            "last_watered": result.get("last_watered"),
            "water_percent": result.get("water_percent", 0),
            "pending_income": result.get("pending_income", 0),
        }, status=400)

    if result.get("branch_dropped", False):
        messages.success(request, "🌿 Поздравляем! Вам выпала ветка!")

    last_watered_str = localtime(tree.last_watered).strftime("%d.%m.%Y %H:%M") if tree.last_watered else "Никогда"

    response_data = {
        "status": "success",
        "message": "Дерево успешно полито",
        "is_watered": True,
        "branch_dropped": result.get("branch_dropped", False),
        "branches_collected": tree.branches_collected,
        "amount_cf": float(result.get("amount_cf", 0)),
        "amount_ton": float(result.get("amount_ton", 0)),
        "water_percent": tree.get_water_percent(),
        "pending_income": float(tree.get_pending_income()),
        "last_watered": last_watered_str,
    }
    return JsonResponse(response_data)


def upgrade_tree(request, tree_id):
    """
    AJAX-обработчик: повышение уровня дерева (использует ветки).
    """
    user = get_current_user(request)
    if not user:
        return JsonResponse({"status": "error", "message": "Сначала авторизуйтесь"}, status=403)

    tree = get_object_or_404(Tree, id=tree_id, user=user)

    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Требуется метод POST"}, status=400)

    if not tree.can_upgrade():
        return JsonResponse({
            "status": "error",
            "message": "Недостаточно веток для улучшения. Накопите ещё веток."
        }, status=400)

    tree.upgrade()
    return JsonResponse({
        "status": "success",
        "message": f"Дерево улучшено до уровня {tree.level}",
        "new_level": tree.level,
        "new_income": float(tree.income_per_hour)
    })


@csrf_exempt
def collect_income(request, tree_id):
    user = get_current_user(request)
    if not user:
        return JsonResponse({"status": "error", "message": "Сначала авторизуйтесь"}, status=403)
    tree = get_object_or_404(Tree, id=tree_id, user=user)
    if request.method != 'POST':
        return JsonResponse({"status": "error", "message": "Требуется POST"}, status=400)

    now = timezone.now()
    pending = tree.get_pending_income()
    if pending <= 0:
        return JsonResponse({"status": "error", "message": "Нет накопленного дохода"}, status=400)

    if tree.type == 'CF':
        user.cf_balance += pending
        user.save(update_fields=["cf_balance"])
        tree.last_cf_accrued = now
        tree.save(update_fields=["last_cf_accrued"])
    elif tree.type == 'TON':
        from trees.models import TonDistribution
        active_dist = TonDistribution.objects.filter(is_active=True).last()
        if not active_dist or active_dist.left_to_distribute <= 0:
            return JsonResponse({"status": "error", "message": "⛔ Раздача TON не активна или пул закончился"},
                                status=400)

        pending = min(pending, active_dist.left_to_distribute)

        user.ton_balance += pending
        user.save(update_fields=["ton_balance"])

        active_dist.distributed_amount += pending
        if active_dist.distributed_amount >= active_dist.total_amount:
            active_dist.is_active = False
        active_dist.save(update_fields=["distributed_amount", "is_active"])

        tree.last_cf_accrued = now
        tree.save(update_fields=["last_cf_accrued"])


    return JsonResponse({
            "status": "success",
            "collected": float(pending),
            "new_balance_cf": float(user.cf_balance) if tree.type == 'CF' else None,
            "new_balance_ton": float(user.ton_balance) if tree.type == 'TON' else None,
            "message": f"Начислено: {float(pending):.4f} {'FL' if tree.type == 'CF' else 'TON'}!"
        })



def use_shop_item(request, purchase_id):
    success, msg = use_purchase_for_cf_tree(request.user, purchase_id)
    success, message = apply_item_to_tree(request.user, purchase_id)
    from trees.models import Tree
    cf_tree = Tree.objects.get(user=request.user, type='CF')
    messages.info(request, message)
    return redirect('tree_detail', tree_id=cf_tree.id)

def accrue_cf_if_needed(tree, user):
    now = timezone.now()
    last = tree.last_cf_accrued or tree.last_watered or now

    watered_limit = (tree.last_watered + timezone.timedelta(hours=5)) if tree.last_watered else now
    auto_water_limit = tree.auto_water_until if tree.auto_water_until and tree.auto_water_until > now else now
    accrue_until = max(watered_limit, auto_water_limit)

    max_time = min(now, accrue_until)
    seconds_since = (max_time - last).total_seconds()
    hours = int(seconds_since // 3600)
    if hours > 0:
        income = hours * tree.income_per_hour
        user.cf_balance += income
        user.save(update_fields=["cf_balance"])
        tree.last_cf_accrued = last + timezone.timedelta(hours=hours)
        tree.save(update_fields=["last_cf_accrued"])
    return
from django.contrib.auth.decorators import user_passes_test
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
@user_passes_test(lambda u: u.is_superuser)
def start_ton_distribution(request):
    if request.method == "POST":
        total_amount = Decimal(request.POST.get("total_amount"))
        # Закрыть все предыдущие
        TonDistribution.objects.filter(is_active=True).update(is_active=False)
        dist = TonDistribution.objects.create(total_amount=total_amount, is_active=True)
        messages.success(request, f"Запущена новая раздача: {total_amount} TON.")
    return redirect("home")


@csrf_exempt
@user_passes_test(lambda u: u.is_superuser)
def finish_ton_distribution(request, dist_id):
    if request.method == "POST":
        dist = TonDistribution.objects.get(id=dist_id)
        dist.finish()
        messages.success(request, "Раздача завершена.")
    return redirect("home")
