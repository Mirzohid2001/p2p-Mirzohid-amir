import datetime
import hashlib
import random

from _decimal import Decimal, InvalidOperation
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.views.decorators.http import require_POST

from trees.models import BurnedToken
from users.models import User
from .models import Order, PriceHistory, P2PSettings
from django.template.loader import render_to_string
import requests

def get_today_cf_price():
    today = timezone.now().date()

    # если цена уже есть за сегодня — просто вернём
    today_obj = PriceHistory.objects.filter(date=today).first()
    if today_obj:
        return float(today_obj.price)

    prev = PriceHistory.objects.filter(date__lt=today).order_by('-date').first()
    prev_price = float(prev.price) if prev else 1.0

    # проверяем рынок
    settings = P2PSettings.objects.first()
    market_open = settings.is_market_open if settings else True

    # если рынок закрыт — НЕ повышаем и НЕ создаём запись за сегодня
    if not market_open:
        return prev_price

    # рынок открыт — создаём цену +1
    new_price = prev_price + 1
    PriceHistory.objects.create(date=today, price=new_price)
    return float(new_price)

def get_ton_to_rub():
    try:
        # 1. Курс TON к USD
        r1 = requests.get('https://min-api.cryptocompare.com/data/price?fsym=TON&tsyms=USD', timeout=5)
        r1.raise_for_status()
        ton_usd = float(r1.json()['USD'])

        # 2. Курс USD к RUB (ЦБ РФ)
        r2 = requests.get('https://www.cbr-xml-daily.ru/daily_json.js', timeout=5)
        r2.raise_for_status()
        usd_rub = float(r2.json()['Valute']['USD']['Value'])

        ton_rub = ton_usd * usd_rub
        # Если вдруг что-то пошло не так — возвращаем 0
        return round(ton_rub, 2) if ton_rub > 0 else 0
    except Exception as e:
        print("Ошибка получения TON к рублю (через CryptoCompare+CBR):", e)
        return 0  # Не возвращай 85.0, лучше 0 чтобы на фронте показать ошибку

def p2p_market(request):
    cf_created = 25000000  # Всегда фиксированное количество
    burned = BurnedToken.objects.aggregate(total=Sum('amount'))['total'] or 0
    cf_grown = User.objects.aggregate(total=Sum('cf_balance'))['total'] or 0  # Сколько всего выращено (на счетах)
    cf_left = cf_created - cf_grown - burned

    ton_to_rub = get_ton_to_rub()
    cf_price_rub = get_today_cf_price()
    ton_per_cf = round(cf_price_rub / ton_to_rub, 8) if ton_to_rub else None
    settings = P2PSettings.objects.first()
    market_open = settings.is_market_open if settings else True
    recent_trades = (
        Order.objects.filter(action='sell', is_active=False, fulfilled_by__isnull=False)
        .select_related('user', 'fulfilled_by')
        .order_by('-fulfilled_at')[:10]
    )

    return render(request, "p2p/market.html", {
        "cf_created": cf_created,
        "cf_grown": cf_grown,
        "cf_left":cf_left,
        "ton_per_cf": ton_per_cf,
        "cf_price_rub": cf_price_rub,
        "ton_to_rub": ton_to_rub,
        "error_no_ton": ton_to_rub == 0,
        "recent_trades": recent_trades,
        "market_open": market_open,
    })


@require_POST
def create_order_sell(request):
    settings = P2PSettings.objects.first()
    if settings and not settings.is_market_open:
        return JsonResponse({"success": False, "msg": "P2P рынок временно закрыт."})

    try:
        cf_amount = Decimal(request.POST.get('cf_amount', '0'))
    except InvalidOperation:
        return JsonResponse({"success": False, "msg": "Некорректное число CF."})

    if cf_amount <= 0:
        return JsonResponse({"success": False, "msg": "Введите положительное число CF."})

    user = request.user
    user.refresh_from_db()
    if user.cf_balance < cf_amount:
        return JsonResponse({"success": False, "msg": "Недостаточно CF на балансе."})

    ton_to_rub = get_ton_to_rub()
    cf_price_rub = get_today_cf_price()
    ton_per_cf = round(float(cf_price_rub) / float(ton_to_rub), 8) if ton_to_rub else 0

    with transaction.atomic():
        user.cf_balance -= cf_amount
        user.save(update_fields=['cf_balance'])
        order = Order.objects.create(
            user=user,
            action="sell",
            cf_amount=cf_amount,
            price_rub=cf_price_rub,
            ton_to_rub=ton_to_rub,
        )

    return JsonResponse({
        "success": True,
        "msg": f"Ордер на продажу {cf_amount} FL создан по {cf_price_rub}₽/FL ({ton_per_cf} TON/FL)"
    })

from django.db.models import Q

def buy_ajax(request):
    sort = request.GET.get('sort', 'price_asc')
    min_amount = request.GET.get('min_amount')
    orders = Order.objects.filter(action='sell', is_active=True)

    # Фильтр по количеству (если передан)
    if min_amount:
        try:
            min_amount = float(min_amount)
            orders = orders.filter(cf_amount__gte=min_amount)
        except ValueError:
            pass

    # Сортировка
    if sort == 'price_asc':
        orders = orders.order_by('price_rub')
    elif sort == 'price_desc':
        orders = orders.order_by('-price_rub')
    elif sort == 'amount_asc':
        orders = orders.order_by('cf_amount')
    elif sort == 'amount_desc':
        orders = orders.order_by('-cf_amount')
    else:
        orders = orders.order_by('price_rub')

    return render(request, 'p2p/_buy_orders.html', {'orders': orders})



def ensure_today_price():
    today = timezone.now().date()
    last_price_obj = PriceHistory.objects.order_by('-date').first()
    if not last_price_obj:
        price = 1
    elif last_price_obj.date == today:
        price = float(last_price_obj.price)
    else:
        price = float(last_price_obj.price) + 1
    obj, created = PriceHistory.objects.get_or_create(
        date=today, defaults={'price': price}
    )
    return obj.price

def generate_fake_candles(n=90, base=15.0, seed=777):
    random.seed(seed)
    candles = []
    prev_close = base
    date = datetime.datetime.now() - datetime.timedelta(days=n)
    for i in range(n):
        open_ = prev_close
        close = open_ + random.uniform(-1, 1)
        high = max(open_, close) + random.uniform(0.1, 0.7)
        low = min(open_, close) - random.uniform(0.1, 0.7)
        high = max(high, open_, close)
        low = min(low, open_, close)
        candles.append({
            "time": int(date.timestamp()),
            "open": round(open_, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2)
        })
        prev_close = close
        date += datetime.timedelta(days=1)
    return candles


def _demo_candles_same_for_all(n=72, base=2.0, interval_minutes=60):
    """
    Красивые свечи (рост/падение), одинаковые для всех пользователей.
    Детерминированно по дате: в течение суток у всех одинаково.
    Последняя свеча close привязана к base.
    """
    now = timezone.now().replace(second=0, microsecond=0)
    day_anchor = now.date().toordinal()

    rng = random.Random(777 + day_anchor)

    step = datetime.timedelta(minutes=interval_minutes)
    start = now - step * n

    candles = []
    prev_close = float(base)

    vol = max(0.01, float(base) * 0.006)  # амплитуда

    for i in range(n):
        t = start + step * i
        open_ = prev_close

        # блоковый дрейф (серии рост/падение)
        block = (i // 6) % 6
        drift = {0: 0.15, 1: 0.08, 2: -0.05, 3: -0.18, 4: 0.10, 5: -0.02}.get(block, 0.0)
        drift = drift * vol * 0.12

        change = rng.uniform(-vol, vol) * 0.55 + drift
        close = max(0.01, open_ + change)

        wick_up = abs(rng.uniform(0.05, 1.0)) * vol * 0.35
        wick_dn = abs(rng.uniform(0.05, 1.0)) * vol * 0.35

        high = max(open_, close) + wick_up
        low = max(0.01, min(open_, close) - wick_dn)

        candles.append({
            "time": int(t.timestamp()),
            "open": round(open_, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
        })

        prev_close = close

    # сдвиг так, чтобы последняя close == base
    if candles:
        delta = float(base) - float(candles[-1]["close"])
        for c in candles:
            c["open"] = round(max(0.01, c["open"] + delta), 2)
            c["high"] = round(max(c["high"] + delta, c["open"], c["close"]), 2)
            c["low"]  = round(min(c["low"] + delta, c["open"], c["close"]), 2)
            c["close"] = round(max(0.01, c["close"] + delta), 2)
        candles[-1]["close"] = round(float(base), 2)

    return candles


def price_history_json(request):
    cf_price_rub = get_today_cf_price()  # как и было — реальная “текущая” цена
    candles = _demo_candles_same_for_all(
        n=72,
        base=float(cf_price_rub),
        interval_minutes=60
    )
    return JsonResponse({"history": candles})

@require_POST
def buy_order(request):
    settings = P2PSettings.objects.first()
    if settings and not settings.is_market_open:
        return JsonResponse({"success": False, "msg": "P2P рынок временно закрыт."})

    try:
        order_id = int(request.POST.get('order_id', '0'))
    except (ValueError, TypeError):
        return JsonResponse({"success": False, "msg": "Некорректный номер ордера."})

    try:
        order = Order.objects.select_for_update().get(id=order_id, is_active=True, action='sell')
    except Order.DoesNotExist:
        return JsonResponse({"success": False, "msg": "Ордер не найден или уже исполнен."})

    buyer = request.user
    seller = order.user
    if buyer == seller:
        return JsonResponse({"success": False, "msg": "Нельзя купить свой ордер."})

    # Рассчитываем сколько TON требуется
    price_in_ton = order.price_in_ton  # уже float с округлением
    total_ton = Decimal(price_in_ton) * order.cf_amount
    total_ton_display = f"{total_ton:.5f}"

    buyer.refresh_from_db()
    seller.refresh_from_db()

    if buyer.ton_balance < total_ton:
        return JsonResponse({"success": False, "msg": f"Недостаточно TON. Нужно {total_ton_display} TON, у вас {buyer.ton_balance}."})

    with transaction.atomic():
        # Списываем TON с покупателя
        buyer.ton_balance -= total_ton
        # Добавляем CF покупателю
        buyer.cf_balance += order.cf_amount
        buyer.save(update_fields=['ton_balance', 'cf_balance'])

        # Продавцу зачисляем TON
        seller.ton_balance += total_ton
        seller.save(update_fields=['ton_balance'])

        # Завершаем ордер
        order.is_active = False
        order.fulfilled_by = buyer
        order.fulfilled_at = timezone.now()
        order.save(update_fields=['is_active', 'fulfilled_by', 'fulfilled_at'])

    return JsonResponse({
        "success": True,
        "msg": f"Вы успешно купили {order.cf_amount} FL за {total_ton:.3f} TON."
    })

def p2p_status(request):
    settings = P2PSettings.objects.first()
    return JsonResponse({"open": settings.is_market_open if settings else True})
