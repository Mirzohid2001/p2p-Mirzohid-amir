from _decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_POST

from trees.models import Tree, BurnedToken
from trees.utils import use_purchase_for_cf_tree
from trees.views import get_current_user
from users.models import User
from .models import ShopItem, Purchase
from django.utils import timezone

def shop(request):
    """Страница магазина"""
    # Получаем все доступные товары
    items = ShopItem.objects.filter(is_active=True)
    user = get_current_user(request)
    ton_tree = Tree.objects.filter(user=user, type='TON').first()
    auto_water_24 = next((item for item in items if 'автополив' in item.name.lower() and '24' in item.name), None)
    auto_water_48 = next((item for item in items if 'автополив' in item.name.lower() and '48' in item.name), None)
    fertilizer = next((item for item in items if 'удобрение' in item.name.lower()), None)
    TOTAL_CREATED_CF = 25_000_000
    all_cf_grown = User.objects.aggregate(total=Sum('cf_balance'))['total'] or 0
    burned = BurnedToken.objects.aggregate(total=Sum('amount'))['total'] or 0
    cf_left = TOTAL_CREATED_CF - all_cf_grown - burned
    from django.utils import timezone
    now = timezone.now()
    purchases = Purchase.objects.filter(
        user=user
    ).select_related('item').order_by('-valid_until')

    return render(request, 'shop/index.html', {
        'items': items,
        'user': user,
        'ton_tree': ton_tree,
        'user_has_ton_tree': bool(ton_tree),
        'auto_water_24_id': auto_water_24.id if auto_water_24 else None,
        'auto_water_48_id': auto_water_48.id if auto_water_48 else None,
        'fertilizer_id': fertilizer.id if fertilizer else None,
        'total_created_cf': TOTAL_CREATED_CF,
        "cf_left": cf_left,
        'all_cf_grown': all_cf_grown,
        'purchases': purchases,
    })

@require_POST
def buy_auto_water(request):
    user = get_current_user(request)
    tree_id = request.POST.get("tree_id")  # Можешь сохранять связь с деревом, но НЕ активируй!
    days = int(request.POST.get("days", 1))  # 1 или 2 суток
    ton_price = Decimal('0.1') if days == 1 else Decimal('0.2')

    if user.ton_balance < ton_price:
        return JsonResponse({"status": "error", "message": "Недостаточно TON"}, status=400)

    # Найти нужный товар
    item = ShopItem.objects.filter(type='auto_water', duration=days*24).first()
    if not item:
        return JsonResponse({"status": "error", "message": "Товар не найден"}, status=400)

    # Списать TON
    user.ton_balance -= ton_price
    user.save(update_fields=["ton_balance"])
    # Добавить в инвентарь
    Purchase.objects.create(user=user, item=item, price_paid=ton_price, valid_until=None)
    return JsonResponse({"status": "success", "message": f"{item.name} добавлен в инвентарь! Активировать можно с этой страницы или на дереве."})

@require_POST

def buy_shop_item(request, item_id):
    user = get_current_user(request)
    item = get_object_or_404(ShopItem, id=item_id, is_active=True)
    price = item.price

    # Спишем токены
    if item.price_token_type == 'CF':
        if user.cf_balance < price:
            return JsonResponse({"status": "error", "message": "Недостаточно CF"}, status=400)
        user.cf_balance -= price
        user.save(update_fields=["cf_balance"])
    elif item.price_token_type == 'TON':
        if user.ton_balance < price:
            return JsonResponse({"status": "error", "message": "Недостаточно TON"}, status=400)
        user.ton_balance -= price
        user.save(update_fields=["ton_balance"])

    valid_until = timezone.now() + timezone.timedelta(hours=item.duration) if item.duration else None
    Purchase.objects.create(user=user, item=item, price_paid=price, valid_until=valid_until)
    from django.contrib import messages
    messages.success(request, f"{item.name} куплен и добавлен в инвентарь!")
    return redirect('shop:shop')
@require_POST
def use_shop_item(request, purchase_id):
    user = get_current_user(request)
    purchase = get_object_or_404(Purchase, id=purchase_id, user=user)

    tree_id = request.POST.get("tree_id")
    if not tree_id:
        # fallback: если только одно дерево, берем его
        trees = Tree.objects.filter(user=user)
        if trees.count() == 1:
            tree = trees.first()
        else:
            return JsonResponse({"status": "error", "message": "Выберите дерево для применения."})
    else:
        tree = get_object_or_404(Tree, id=tree_id, user=user)

    # Проверяем не истекло ли действие
    if purchase.valid_until and timezone.now() > purchase.valid_until:
        purchase.delete()
        return JsonResponse({"status": "error", "message": "Срок действия предмета истёк. Предмет удалён из инвентаря."})

    # ---- Автополив ----
    if purchase.item.type == 'auto_water':
        if tree.auto_water_until and tree.auto_water_until > timezone.now():
            return JsonResponse({"status": "error", "message": "Автополив уже активен!"})
        hours = purchase.item.duration or 24
        tree.auto_water_until = timezone.now() + timezone.timedelta(hours=hours)
        tree.save(update_fields=["auto_water_until"])
        purchase.delete()
        return JsonResponse({"status": "success", "message": f"Автополив активирован на {hours}ч!"})

    # ---- Удобрение ----
    if purchase.item.type == 'fertilizer':
        if tree.fertilized_until and tree.fertilized_until > timezone.now():
            return JsonResponse({"status": "error", "message": "Удобрение уже активно!"})
        hours = purchase.item.duration or 24
        tree.fertilized_until = timezone.now() + timezone.timedelta(hours=hours)
        tree.save(update_fields=["fertilized_until"])
        purchase.delete()
        return JsonResponse({"status": "success", "message": "Дерево удобрено (доход ×2)!"})

    return JsonResponse({"status": "error", "message": "Неизвестный предмет."})



@require_POST
def buy_fertilizer(request):
    user = get_current_user(request)
    tree_id = request.POST.get("tree_id")
    ton_price = Decimal('0.1')

    if user.ton_balance < ton_price:
        return JsonResponse({"status": "error", "message": "Недостаточно TON"}, status=400)
    item = ShopItem.objects.filter(type='fertilizer').first()
    if not item:
        return JsonResponse({"status": "error", "message": "Товар не найден"}, status=400)
    # Списать TON
    user.ton_balance -= ton_price
    user.save(update_fields=["ton_balance"])
    # Добавить в инвентарь
    Purchase.objects.create(user=user, item=item, price_paid=ton_price, valid_until=None)
    return JsonResponse({
        "status": "success",
        "message": "Удобрение успешно куплено!"
    })

@require_POST
def buy_branches(request):
    user = get_current_user(request)

    try:
        quantity = int(request.POST.get("quantity", 1))
    except Exception:
        quantity = 1

    ton_price = Decimal('0.5') * quantity

    if user.ton_balance < ton_price:
        return JsonResponse({"status": "error", "message": "Недостаточно TON для покупки веток."}, status=400)

    user.ton_balance -= ton_price
    user.branches_balance += quantity
    user.save(update_fields=["ton_balance", "branches_balance"])

    return JsonResponse({
        "status": "success",
        "message": f"Куплено веток: {quantity}. Теперь у вас {user.branches_balance} веток."
    })


def buy_ton_tree(request):
    user = get_current_user(request)
    if not user:
        return redirect("telegram_login")

    # Проверка, что у пользователя ещё нет TON-дерева
    if Tree.objects.filter(user=user, type='TON').exists():
        messages.warning(request, "У вас уже есть TON-дерево.")
        return redirect("home")

    cost_ton = 5
    if user.ton_balance < cost_ton:
        messages.error(request, "Недостаточно TON для покупки TON-дерева.")
        return redirect("home")


    user.ton_balance -= cost_ton
    user.save(update_fields=["ton_balance"])
    Tree.objects.create(user=user, type="TON")

    messages.success(request, "TON-дерево успешно куплено!")
    return redirect("home")


