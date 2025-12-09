from decimal import Decimal, ROUND_DOWN, InvalidOperation
from django.db import transaction, models
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, authenticate
from django.contrib import messages
from django.http import JsonResponse, HttpResponseRedirect
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Sum, Avg, F, Q, Case, When, DecimalField
from django.db.models.functions import TruncDate
from django.core.paginator import Paginator
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.conf import settings
import hashlib
import hmac
import base64
import json
import time
import urllib.parse
from datetime import datetime, timedelta
import logging

from .models import Tree, Order, Transaction, OrderCancelLog, User, SpecialTree, Donation, AdSlot, AdPurchase, P2POrder, P2POrderCancelLog, TelegramUser, TreeType, TreePurchaseTransaction, WaterLog, UpgradeLog
from .services import (
    water_tree, auto_water_tree, fertilize_tree, create_staking, upgrade_tree, 
    buy_special_tree, generate_referral_code, apply_referral_code, get_referral_stats,
    notify, purchase_tree_type
)
from .tasks import expire_order, get_weekly_ad_income
from .utils.notify import notify

# Главная страница - выбор деревьев
@login_required
def home(request):
    """Главная страница с выбором деревьев"""
    trees = Tree.objects.filter(owner=request.user)
    tree_types = TreeType.objects.all()
    
    # Tree types with ownership info
    tree_types_with_info = []
    for tree_type in tree_types:
        is_owned = Tree.objects.filter(owner=request.user, tree_type=tree_type).exists()
        tree_types_with_info.append({
            'tree_type': tree_type,
            'is_owned': is_owned
        })
    
    # User statistics
    user_stats = {
        'total_trees': trees.count(),
        'total_cf_earned': Transaction.objects.filter(
            user=request.user,
            currency='CF',
            type__in=['water', 'passive_water']
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0'),
        'total_orders': Order.objects.filter(seller=request.user).count(),
    }
    
    context = {
        'trees': trees,
        'tree_types': tree_types,
        'tree_types_with_info': tree_types_with_info,
        'user_stats': user_stats,
        'user': request.user,
    }
    return render(request, 'farm/home.html', context)

# Страница конкретного дерева
@login_required
def tree_detail(request, tree_id):
    """Страница управления конкретным деревом"""
    tree = get_object_or_404(Tree, id=tree_id, owner=request.user)
    
    # Подсчитываем ветки
    total_branches = sum(log.branches for log in tree.upgrade_logs.all())
    
    # Проверяем статус полива
    from .services import is_watered, UPGRADE_REQ_BRANCH
    is_tree_watered = is_watered(tree)
    
    # Hourly income calculation
    if not tree.tree_type:
        hourly_income = 1.0  # Базовое дерево CF
        income_currency = 'CF'
    else:
        base_income = tree.tree_type.hourly_income
        if tree.fertilizer_expires and tree.fertilizer_expires > timezone.now():
            hourly_income = float(base_income * 2)
        else:
            hourly_income = float(base_income)
        income_currency = tree.tree_type.income_currency
    
    # Next level branches requirement
    next_level_branches = None
    if tree.level < 5:
        next_level_branches = UPGRADE_REQ_BRANCH.get(tree.level + 1)
    
    # Total earned by this tree
    total_earned = sum(
        log.amount for log in tree.water_logs.filter(currency=income_currency)
    )
    
    # Can use check
    can_use = True
    if tree.tree_type and tree.tree_type.price_ton > 0:
        can_use = TreePurchaseTransaction.objects.filter(
            user=tree.owner,
            tree_type=tree.tree_type,
            status="completed"
        ).exists()
    
    # Recent water logs
    recent_water_logs = tree.water_logs.order_by('-timestamp')[:10]
    
    # Recent upgrade logs
    recent_upgrade_logs = tree.upgrade_logs.order_by('-timestamp')[:5]
    
    context = {
        'tree': tree,
        'total_branches': total_branches,
        'is_watered': is_tree_watered,
        'hourly_income': hourly_income,
        'income_currency': income_currency,
        'next_level_branches': next_level_branches,
        'total_earned': total_earned,
        'can_use': can_use,
        'recent_water_logs': recent_water_logs,
        'recent_upgrade_logs': recent_upgrade_logs,
        'user': request.user,
    }
    return render(request, 'farm/tree_detail.html', context)

# Полив дерева
@login_required
@require_POST
def water_tree_view(request, tree_id):
    """Полив дерева"""
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        tree = get_object_or_404(Tree.objects.select_for_update(), pk=tree_id, owner=user)
        
        try:
            result = water_tree(tree, user)
            messages.success(request, f"Дерево полито! Получено {result['amount']} {result['currency']}")
        except ValueError as exc:
            messages.error(request, str(exc))
    
    return redirect('tree_detail', tree_id=tree_id)

# Автополив
@login_required
@require_POST
def auto_water_tree_view(request, tree_id):
    """Включение автополива"""
    tree = get_object_or_404(Tree, id=tree_id, owner=request.user)
    hours = int(request.POST.get('hours', 24))
    
    try:
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            tree = Tree.objects.select_for_update().get(pk=tree_id)
            
            price = auto_water_tree(tree, user, hours)
            messages.success(request, f"Автополив включен на {hours} часов. Списано {price} CF")
    except ValueError as exc:
        messages.error(request, str(exc))
    
    return redirect('tree_detail', tree_id=tree_id)

# Удобрение
@login_required
@require_POST
def fertilize_tree_view(request, tree_id):
    """Удобрение дерева"""
    tree = get_object_or_404(Tree, id=tree_id, owner=request.user)
    
    try:
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            tree = Tree.objects.select_for_update().get(pk=tree_id)
            
            price = fertilize_tree(tree, user)
            messages.success(request, f"Дерево удобрено! Списано {price} CF")
    except ValueError as exc:
        messages.error(request, str(exc))
    
    return redirect('tree_detail', tree_id=tree_id)

# Улучшение дерева
@login_required
@require_POST
def upgrade_tree_view(request, tree_id):
    """Улучшение дерева"""
    tree = get_object_or_404(Tree, id=tree_id, owner=request.user)
    
    success = upgrade_tree(tree)
    if success:
        messages.success(request, f"Дерево улучшено до {tree.level} уровня!")
    else:
        messages.error(request, "Недостаточно веток для улучшения")
    
    return redirect('tree_detail', tree_id=tree_id)

# Создание нового дерева
@login_required
def create_tree(request):
    """Создание нового дерева"""
    if request.method == 'POST':
        tree_type_id = request.POST.get('tree_type_id')
        transaction_hash = request.POST.get('transaction_hash')
        
        try:
            tree_type = TreeType.objects.get(id=tree_type_id)
            
            # Проверяем, есть ли уже такое дерево у пользователя
            if Tree.objects.filter(owner=request.user, tree_type=tree_type).exists():
                messages.error(request, "У вас уже есть дерево этого типа")
                return redirect('home')
            
            # Если дерево платное, но нет хэша транзакции
            if tree_type.price_ton > 0 and not transaction_hash:
                context = {
                    'tree_type': tree_type,
                    'system_wallet': settings.SYSTEM_TON_WALLET
                }
                return render(request, 'farm/payment_required.html', context)
            
            # Создаем дерево через сервис
            tree = purchase_tree_type(request.user, tree_type_id, transaction_hash)
            messages.success(request, f"Дерево {tree_type.name} успешно создано!")
            return redirect('tree_detail', tree_id=tree.id)
            
        except TreeType.DoesNotExist:
            messages.error(request, "Тип дерева не найден")
        except ValueError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, "Произошла ошибка при создании дерева")
    
    return redirect('home')

# Рынок - список ордеров
@login_required
def market(request):
    """Страница рынка с ордерами"""
    orders = Order.objects.filter(status="open").order_by('-created_at')
    
    # Фильтрация
    order_type = request.GET.get('type')
    if order_type in ['sell', 'buy']:
        orders = orders.filter(order_type=order_type)
    
    min_price = request.GET.get('min_price')
    if min_price:
        try:
            orders = orders.filter(price_ton__gte=Decimal(min_price))
        except:
            pass
    
    max_price = request.GET.get('max_price')
    if max_price:
        try:
            orders = orders.filter(price_ton__lte=Decimal(max_price))
        except:
            pass
    
    # Сортировка
    ordering = request.GET.get('ordering')
    if ordering in ['price_ton', '-price_ton', 'amount_cf', '-amount_cf']:
        orders = orders.order_by(ordering)
    
    # Пагинация
    paginator = Paginator(orders, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'user': request.user,
        'current_filters': {
            'type': order_type,
            'min_price': min_price,
            'max_price': max_price,
            'ordering': ordering,
        }
    }
    return render(request, 'farm/market.html', context)

# Создание ордера
@login_required
def create_order(request):
    """Создание нового ордера"""
    if request.method == 'POST':
        amount_cf = request.POST.get('amount_cf')
        price_ton = request.POST.get('price_ton')
        order_type = request.POST.get('order_type', Order.SELL)
        
        try:
            amount = Decimal(amount_cf)
            price = Decimal(price_ton)
            
            if amount <= 0 or price <= 0:
                messages.error(request, "Сумма и цена должны быть больше нуля")
                return redirect('market')
            
            with transaction.atomic():
                user = User.objects.select_for_update().get(pk=request.user.pk)
                
                if order_type == Order.SELL:
                    if user.balance_cf < amount:
                        messages.error(request, "Недостаточно CF")
                        return redirect('market')
                    user.balance_cf -= amount
                else:
                    ton_required = (price * amount).quantize(Decimal("0.00000001"))
                    if user.balance_ton < ton_required:
                        messages.error(request, "Недостаточно TON")
                        return redirect('market')
                    user.balance_ton -= ton_required
                
                user.save()
                
                order = Order.objects.create(
                    seller=user,
                    amount_cf=amount,
                    price_ton=price,
                    order_type=order_type,
                    expires_at=timezone.now() + timedelta(days=3)
                )
                
                Transaction.objects.create(
                    user=user, type="order_create", amount=amount, currency="CF"
                )
                
                messages.success(request, "Ордер успешно создан!")
                
        except (ValueError, InvalidOperation):
            messages.error(request, "Неверный формат числа")
        except Exception as e:
            messages.error(request, "Произошла ошибка при создании ордера")
    
    return redirect('market')

# Покупка по ордеру
@login_required
@require_POST
def buy_order(request, order_id):
    """Покупка по существующему ордеру"""
    order = get_object_or_404(Order, id=order_id, status="open")
    
    if order.seller == request.user:
        messages.error(request, "Нельзя купить свой собственный ордер")
        return redirect('market')
    
    try:
        with transaction.atomic():
            buyer = User.objects.select_for_update().get(pk=request.user.pk)
            seller = User.objects.select_for_update().get(pk=order.seller.pk)
            order = Order.objects.select_for_update().get(pk=order_id)
            
            if order.order_type == Order.SELL:
                # Покупатель платит TON, получает CF
                total_ton = (order.price_ton * order.amount_cf).quantize(Decimal("0.00000001"))
                if buyer.balance_ton < total_ton:
                    messages.error(request, "Недостаточно TON")
                    return redirect('market')
                
                buyer.balance_ton -= total_ton
                buyer.balance_cf += order.amount_cf
                seller.balance_ton += total_ton
                
            else:  # BUY order
                # Покупатель платит CF, получает TON
                if buyer.balance_cf < order.amount_cf:
                    messages.error(request, "Недостаточно CF")
                    return redirect('market')
                
                total_ton = (order.price_ton * order.amount_cf).quantize(Decimal("0.00000001"))
                buyer.balance_cf -= order.amount_cf
                buyer.balance_ton += total_ton
                seller.balance_cf += order.amount_cf
            
            buyer.save()
            seller.save()
            
            order.status = "filled"
            order.save()
            
            # Создаем транзакции
            Transaction.objects.create(
                user=buyer, type="order_buy", amount=order.amount_cf, currency="CF"
            )
            Transaction.objects.create(
                user=seller, type="order_sell", amount=order.amount_cf, currency="CF"
            )
            
            messages.success(request, "Ордер успешно выполнен!")
            
    except Exception as e:
        messages.error(request, "Произошла ошибка при выполнении ордера")
    
    return redirect('market')

# Отмена ордера
@login_required
@require_POST
def cancel_order(request, order_id):
    """Отмена ордера"""
    order = get_object_or_404(Order, id=order_id, seller=request.user, status="open")
    
    try:
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            order = Order.objects.select_for_update().get(pk=order_id)
            
            # Возвращаем средства
            if order.order_type == Order.SELL:
                user.balance_cf += order.amount_cf
            else:
                ton_amount = (order.price_ton * order.amount_cf).quantize(Decimal("0.00000001"))
                user.balance_ton += ton_amount
            
            user.save()
            
            order.status = "cancelled"
            order.save()
            
            OrderCancelLog.objects.create(
                order=order,
                refunded_amount=order.amount_cf
            )
            
            messages.success(request, "Ордер отменен, средства возвращены")
            
    except Exception as e:
        messages.error(request, "Произошла ошибка при отмене ордера")
    
    return redirect('market')

# История транзакций
@login_required
def transactions(request):
    """Страница истории транзакций"""
    user_transactions = Transaction.objects.filter(user=request.user).order_by('-timestamp')
    
    # Пагинация
    paginator = Paginator(user_transactions, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'user': request.user,
    }
    return render(request, 'farm/transactions.html', context)

# Профиль пользователя
@login_required
def profile(request):
    """Страница профиля пользователя"""
    # Статистика рефералов
    referral_stats = get_referral_stats(request.user)
    
    # Последние транзакции
    recent_transactions = Transaction.objects.filter(user=request.user).order_by('-timestamp')[:5]
    
    # Статистика деревьев
    trees_count = Tree.objects.filter(owner=request.user).count()
    
    context = {
        'user': request.user,
        'referral_stats': referral_stats,
        'recent_transactions': recent_transactions,
        'trees_count': trees_count,
    }
    return render(request, 'farm/profile.html', context)

# Реферальная система
@login_required
def referrals(request):
    """Страница реферальной системы"""
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'generate':
            code = generate_referral_code(request.user)
            messages.success(request, f"Ваш реферальный код: {code}")
        
        elif action == 'apply':
            code = request.POST.get('code')
            try:
                result = apply_referral_code(request.user, code)
                messages.success(request, f"Код применен! Вы получили {result['bonus_invited']} CF")
            except ValueError as e:
                messages.error(request, str(e))
    
    stats = get_referral_stats(request.user)
    
    context = {
        'user': request.user,
        'stats': stats,
    }
    return render(request, 'farm/referrals.html', context)

# P2P торговля
@login_required
def p2p_market(request):
    """P2P рынок"""
    # Обновляем статус истекших ордеров
    expired_orders = P2POrder.objects.filter(
        status=P2POrder.OPEN,
        expires_at__lt=timezone.now()
    )
    for order in expired_orders:
        order.status = P2POrder.EXPIRED
        order.save()
        # Возвращаем средства
        order.seller.balance_cf += order.amount_cf
        order.seller.save()
    
    orders = P2POrder.objects.filter(status=P2POrder.OPEN).order_by('-created_at')
    
    # Пагинация
    paginator = Paginator(orders, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'user': request.user,
    }
    return render(request, 'farm/p2p_market.html', context)

# Мои P2P ордера
@login_required
def my_p2p_orders(request):
    """Мои P2P ордера"""
    orders = P2POrder.objects.filter(seller=request.user).order_by('-created_at')
    
    # Пагинация
    paginator = Paginator(orders, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'user': request.user,
    }
    return render(request, 'farm/my_p2p_orders.html', context)

# Специальные деревья
@login_required
def special_trees(request):
    """Страница специальных деревьев"""
    user_special_trees = SpecialTree.objects.filter(owner=request.user)
    
    context = {
        'user': request.user,
        'special_trees': user_special_trees,
    }
    return render(request, 'farm/special_trees.html', context)

# Покупка специального дерева
@login_required
@require_POST
def buy_special_tree_view(request, kind):
    """Покупка специального дерева"""
    try:
        result = buy_special_tree(request.user, kind)
        messages.success(request, f"Специальное дерево {kind} куплено!")
    except ValueError as e:
        messages.error(request, str(e))
    
    return redirect('special_trees')

# Telegram авторизация
@csrf_exempt
def telegram_auth(request):
    """Авторизация через Telegram"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            # Здесь должна быть проверка подписи Telegram
            # Упрощенная версия для примера
            
            tg_id = data.get('id')
            username = data.get('username', f'user_{tg_id}')
            first_name = data.get('first_name', '')
            
            # Создаем или получаем пользователя
            user, created = User.objects.get_or_create(
                tg_id=tg_id,
                defaults={
                    'username': username,
                    'first_name': first_name,
                }
            )
            
            # Авторизуем пользователя
            login(request, user)
            
            return JsonResponse({'success': True})
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    
    return render(request, 'farm/telegram_auth.html')

# Админ аналитика
@staff_member_required
def admin_analytics(request):
    """Админ панель с аналитикой"""
    # Общая статистика
    total_users = User.objects.count()
    total_trees = Tree.objects.count()
    total_orders = Order.objects.count()
    
    # Статистика по дням
    daily_stats = (
        User.objects
        .extra({'date': "date(date_joined)"})
        .values('date')
        .annotate(count=Count('id'))
        .order_by('-date')[:30]
    )
    
    context = {
        'total_users': total_users,
        'total_trees': total_trees,
        'total_orders': total_orders,
        'daily_stats': daily_stats,
    }
    return render(request, 'farm/admin_analytics.html', context)

# Staking (Steking) funksiyalari
@login_required
def staking_list(request):
    """Staking sahifasi"""
    from .models import Staking
    
    user_stakings = Staking.objects.filter(user=request.user).order_by('-started_at')
    
    # Staking statistikasi
    total_staked = user_stakings.filter(completed=False).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0')
    
    context = {
        'stakings': user_stakings,
        'total_staked': total_staked,
        'user': request.user,
    }
    return render(request, 'farm/staking.html', context)

@login_required
@require_POST
def create_staking_view(request):
    """Staking yaratish"""
    amount = request.POST.get('amount')
    duration_days = int(request.POST.get('duration_days', 30))
    
    try:
        amount_decimal = Decimal(amount)
        
        if amount_decimal <= 0:
            messages.error(request, "Miqdor 0 dan katta bo'lishi kerak")
            return redirect('staking_list')
        
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            
            if user.balance_cf < amount_decimal:
                messages.error(request, "Yetarli CF balansi yo'q")
                return redirect('staking_list')
            
            result = create_staking(user, amount_decimal, duration_days)
            messages.success(request, f"Staking yaratildi! {duration_days} kun uchun {amount} CF")
            
    except (ValueError, InvalidOperation):
        messages.error(request, "Noto'g'ri miqdor formati")
    except Exception as e:
        messages.error(request, f"Xatolik: {str(e)}")
    
    return redirect('staking_list')

# Donation (Xayriya) funksiyalari
@login_required
def donations(request):
    """Xayriya sahifasi"""
    user_donations = Donation.objects.filter(user=request.user).order_by('-created_at')
    
    # Umumiy xayriya statistikasi
    total_donated = user_donations.aggregate(total=Sum('amount_cf'))['total'] or Decimal('0')
    
    # Oxirgi xayriyalar (barcha foydalanuvchilar)
    recent_donations = Donation.objects.order_by('-created_at')[:10]
    
    context = {
        'user_donations': user_donations,
        'total_donated': total_donated,
        'recent_donations': recent_donations,
        'user': request.user,
    }
    return render(request, 'farm/donations.html', context)

@login_required
@require_POST
def make_donation(request):
    """Xayriya qilish"""
    amount = request.POST.get('amount')
    
    try:
        amount_decimal = Decimal(amount)
        
        if amount_decimal <= 0:
            messages.error(request, "Miqdor 0 dan katta bo'lishi kerak")
            return redirect('donations')
        
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            
            if user.balance_cf < amount_decimal:
                messages.error(request, "Yetarli CF balansi yo'q")
                return redirect('donations')
            
            user.balance_cf -= amount_decimal
            user.save()
            
            # Xayriya yaratish
            Donation.objects.create(
                user=user,
                amount_cf=amount_decimal
            )
            
            # Tranzaksiya yaratish
            Transaction.objects.create(
                user=user,
                type='donation',
                amount=amount_decimal,
                currency='CF',
                description=f'Xayriya: {amount_decimal} CF'
            )
            
            messages.success(request, f"Xayriya qilindi: {amount_decimal} CF")
            
    except (ValueError, InvalidOperation):
        messages.error(request, "Noto'g'ri miqdor formati")
    except Exception as e:
        messages.error(request, f"Xatolik: {str(e)}")
    
    return redirect('donations')

# Reklama funksiyalari
@login_required
def ads_market(request):
    """Reklama bozori"""
    ad_slots = AdSlot.objects.all()
    user_purchases = AdPurchase.objects.filter(user=request.user).order_by('-purchased_at')
    
    context = {
        'ad_slots': ad_slots,
        'user_purchases': user_purchases,
        'user': request.user,
    }
    return render(request, 'farm/ads_market.html', context)

@login_required
@require_POST
def buy_ad_slot(request, slot_id):
    """Reklama slotini sotib olish"""
    slot = get_object_or_404(AdSlot, id=slot_id)
    
    try:
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            
            if user.balance_cf < slot.price_cf:
                messages.error(request, "Yetarli CF balansi yo'q")
                return redirect('ads_market')
            
            user.balance_cf -= slot.price_cf
            user.save()
            
            # Reklama sotib olish
            expires_at = timezone.now() + timedelta(hours=slot.duration_h)
            AdPurchase.objects.create(
                user=user,
                slot=slot,
                expires_at=expires_at
            )
            
            # Tranzaksiya yaratish
            Transaction.objects.create(
                user=user,
                type='ad_purchase',
                amount=slot.price_cf,
                currency='CF',
                description=f'Reklama sotib olindi: {slot.name}'
            )
            
            messages.success(request, f"Reklama sloti sotib olindi: {slot.name}")
            
    except Exception as e:
        messages.error(request, f"Xatolik: {str(e)}")
    
    return redirect('ads_market')

# P2P Order yaratish va boshqarish
@login_required
def create_p2p_order(request):
    """P2P order yaratish"""
    if request.method == 'POST':
        amount_cf = request.POST.get('amount_cf')
        fixed_price_ton = request.POST.get('fixed_price_ton')
        
        try:
            amount = Decimal(amount_cf)
            price = Decimal(fixed_price_ton)
            
            if amount <= 0 or price <= 0:
                messages.error(request, "Miqdor va narx 0 dan katta bo'lishi kerak")
                return redirect('p2p_market')
            
            with transaction.atomic():
                user = User.objects.select_for_update().get(pk=request.user.pk)
                
                if user.balance_cf < amount:
                    messages.error(request, "Yetarli CF balansi yo'q")
                    return redirect('p2p_market')
                
                user.balance_cf -= amount
                user.save()
                
                # P2P order yaratish
                current_market_price = Decimal(getattr(settings, 'CURRENT_CF_PRICE', '0.01'))
                expires_at = timezone.now() + timedelta(days=7)
                
                P2POrder.objects.create(
                    seller=user,
                    amount_cf=amount,
                    fixed_price_ton=price,
                    current_market_price_ton=current_market_price,
                    expires_at=expires_at
                )
                
                messages.success(request, "P2P order yaratildi!")
                
        except (ValueError, InvalidOperation):
            messages.error(request, "Noto'g'ri miqdor formati")
        except Exception as e:
            messages.error(request, f"Xatolik: {str(e)}")
    
    return redirect('p2p_market')

@login_required
@require_POST
def buy_p2p_order(request, order_id):
    """P2P orderni sotib olish"""
    order = get_object_or_404(P2POrder, id=order_id, status=P2POrder.OPEN)
    
    if order.seller == request.user:
        messages.error(request, "O'z orderingizni sotib ola olmaysiz")
        return redirect('p2p_market')
    
    try:
        with transaction.atomic():
            buyer = User.objects.select_for_update().get(pk=request.user.pk)
            seller = User.objects.select_for_update().get(pk=order.seller.pk)
            order = P2POrder.objects.select_for_update().get(pk=order_id)
            
            total_ton = (order.fixed_price_ton * order.amount_cf).quantize(Decimal("0.00000001"))
            
            if buyer.balance_ton < total_ton:
                messages.error(request, "Yetarli TON balansi yo'q")
                return redirect('p2p_market')
            
            # Pul o'tkazmalari
            buyer.balance_ton -= total_ton
            buyer.balance_cf += order.amount_cf
            seller.balance_ton += total_ton
            
            buyer.save()
            seller.save()
            
            # Orderni yangilash
            order.buyer = buyer
            order.status = P2POrder.FILLED
            order.filled_at = timezone.now()
            order.save()
            
            # Tranzaksiyalar yaratish
            Transaction.objects.create(
                user=buyer,
                type='p2p_buy',
                amount=order.amount_cf,
                currency='CF',
                description=f'P2P sotib olindi: {order.amount_cf} CF'
            )
            
            Transaction.objects.create(
                user=seller,
                type='p2p_sell',
                amount=total_ton,
                currency='TON',
                description=f'P2P sotildi: {order.amount_cf} CF'
            )
            
            messages.success(request, "P2P order muvaffaqiyatli bajarildi!")
            
    except Exception as e:
        messages.error(request, f"Xatolik: {str(e)}")
    
    return redirect('p2p_market')

@login_required
@require_POST
def cancel_p2p_order(request, order_id):
    """P2P orderni bekor qilish"""
    order = get_object_or_404(P2POrder, id=order_id, seller=request.user, status=P2POrder.OPEN)
    
    try:
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            order = P2POrder.objects.select_for_update().get(pk=order_id)
            
            # Pulni qaytarish
            user.balance_cf += order.amount_cf
            user.save()
            
            # Orderni bekor qilish
            order.status = P2POrder.CANCELLED
            order.save()
            
            # Log yaratish
            P2POrderCancelLog.objects.create(
                order=order,
                refunded_amount=order.amount_cf
            )
            
            messages.success(request, "P2P order bekor qilindi, pul qaytarildi")
            
    except Exception as e:
        messages.error(request, f"Xatolik: {str(e)}")
    
    return redirect('my_p2p_orders')

# TreePurchaseTransaction boshqaruvi
@login_required
def tree_purchases(request):
    """Daraxt sotib olish tarixi"""
    purchases = TreePurchaseTransaction.objects.filter(user=request.user).order_by('-created_at')
    
    context = {
        'purchases': purchases,
        'user': request.user,
    }
    return render(request, 'farm/tree_purchases.html', context)

@login_required
@require_POST
def confirm_tree_purchase(request):
    """Daraxt sotib olishni tasdiqlash"""
    tree_type_id = request.POST.get('tree_type_id')
    transaction_hash = request.POST.get('transaction_hash')
    
    try:
        tree_type = TreeType.objects.get(id=tree_type_id)
        
        # Avval bunday tranzaksiya borligini tekshirish
        existing = TreePurchaseTransaction.objects.filter(
            transaction_hash=transaction_hash
        ).first()
        
        if existing:
            messages.error(request, "Bu tranzaksiya allaqachon ishlatilgan")
            return redirect('tree_purchases')
        
        # Yangi tranzaksiya yaratish
        purchase = TreePurchaseTransaction.objects.create(
            user=request.user,
            tree_type=tree_type,
            amount_ton=tree_type.price_ton,
            transaction_hash=transaction_hash,
            status='pending'
        )
        
        messages.success(request, "Tranzaksiya yuborildi, tekshirilmoqda...")
        
    except TreeType.DoesNotExist:
        messages.error(request, "Daraxt turi topilmadi")
    except Exception as e:
        messages.error(request, f"Xatolik: {str(e)}")
    
    return redirect('tree_purchases')

# Batafsil statistikalar
@login_required
def detailed_stats(request):
    """Batafsil statistikalar sahifasi"""
    user = request.user
    
    # Daraxt statistikalari
    trees = Tree.objects.filter(owner=user)
    tree_stats = {
        'total_trees': trees.count(),
        'max_level': trees.aggregate(max_level=models.Max('level'))['max_level'] or 0,
        'avg_level': trees.aggregate(avg_level=Avg('level'))['avg_level'] or 0,
    }
    
    # Tranzaksiya statistikalari
    transactions = Transaction.objects.filter(user=user)
    transaction_stats = {
        'total_transactions': transactions.count(),
        'total_earned_cf': transactions.filter(
            currency='CF', 
            type__in=['water', 'passive_water', 'referral_reward']
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0'),
        'total_spent_cf': transactions.filter(
            currency='CF',
            type__in=['order_create', 'auto_water', 'fertilizer', 'donation']
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0'),
    }
    
    # Oxirgi 30 kun statistikasi
    last_30_days = timezone.now() - timedelta(days=30)
    daily_earnings = transactions.filter(
        timestamp__gte=last_30_days,
        currency='CF',
        type__in=['water', 'passive_water']
    ).annotate(
        date=TruncDate('timestamp')
    ).values('date').annotate(
        daily_total=Sum('amount')
    ).order_by('date')
    
    # Referal statistikalari
    referral_stats = get_referral_stats(user)
    
    # Order statistikalari
    order_stats = {
        'total_orders': Order.objects.filter(seller=user).count(),
        'filled_orders': Order.objects.filter(seller=user, status='filled').count(),
        'open_orders': Order.objects.filter(seller=user, status='open').count(),
    }
    
    context = {
        'user': user,
        'tree_stats': tree_stats,
        'transaction_stats': transaction_stats,
        'daily_earnings': list(daily_earnings),
        'referral_stats': referral_stats,
        'order_stats': order_stats,
    }
    return render(request, 'farm/detailed_stats.html', context)

# WaterLog va UpgradeLog ko'rish
@login_required
def water_logs(request, tree_id=None):
    """Poliv loglarini ko'rish"""
    if tree_id:
        tree = get_object_or_404(Tree, id=tree_id, owner=request.user)
        logs = tree.water_logs.order_by('-timestamp')
        context_tree = tree
    else:
        # Barcha daraxtlarning poliv loglari
        user_trees = Tree.objects.filter(owner=request.user)
        logs = WaterLog.objects.filter(tree__in=user_trees).order_by('-timestamp')
        context_tree = None
    
    # Paginatsiya
    paginator = Paginator(logs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'tree': context_tree,
        'user': request.user,
    }
    return render(request, 'farm/water_logs.html', context)

@login_required
def upgrade_logs(request, tree_id=None):
    """Upgrade loglarini ko'rish"""
    if tree_id:
        tree = get_object_or_404(Tree, id=tree_id, owner=request.user)
        logs = tree.upgrade_logs.order_by('-timestamp')
        context_tree = tree
    else:
        # Barcha daraxtlarning upgrade loglari
        user_trees = Tree.objects.filter(owner=request.user)
        logs = UpgradeLog.objects.filter(tree__in=user_trees).order_by('-timestamp')
        context_tree = None
    
    # Paginatsiya
    paginator = Paginator(logs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'tree': context_tree,
        'user': request.user,
    }
    return render(request, 'farm/upgrade_logs.html', context)

# Tree Type boshqaruvi
@login_required
def tree_types(request):
    """Barcha daraxt turlarini ko'rish"""
    tree_types = TreeType.objects.all()
    
    # Har bir tree type uchun foydalanuvchi ma'lumotlari
    tree_types_with_info = []
    for tree_type in tree_types:
        user_tree = Tree.objects.filter(owner=request.user, tree_type=tree_type).first()
        is_owned = user_tree is not None
        
        # Sotib olish holati
        purchase_status = None
        if tree_type.price_ton > 0:
            purchase = TreePurchaseTransaction.objects.filter(
                user=request.user,
                tree_type=tree_type
            ).order_by('-created_at').first()
            if purchase:
                purchase_status = purchase.status
        
        tree_types_with_info.append({
            'tree_type': tree_type,
            'is_owned': is_owned,
            'user_tree': user_tree,
            'purchase_status': purchase_status,
        })
    
    context = {
        'tree_types_with_info': tree_types_with_info,
        'user': request.user,
    }
    return render(request, 'farm/tree_types.html', context)

# Staking batafsil ma'lumotlari
@login_required
def staking_detail(request, staking_id):
    """Staking batafsil ma'lumotlari"""
    from .models import Staking
    
    staking = get_object_or_404(Staking, id=staking_id, user=request.user)
    
    # Staking statistikalari
    days_passed = (timezone.now() - staking.started_at).days
    days_remaining = max(0, staking.duration_days - days_passed)
    progress_percent = min(100, (days_passed / staking.duration_days) * 100)
    
    # Kutilayotgan daromad
    expected_reward = staking.amount * (staking.bonus_percent / 100)
    
    context = {
        'staking': staking,
        'days_passed': days_passed,
        'days_remaining': days_remaining,
        'progress_percent': progress_percent,
        'expected_reward': expected_reward,
        'user': request.user,
    }
    return render(request, 'farm/staking_detail.html', context)

# Telegram foydalanuvchilar boshqaruvi (admin uchun)
@staff_member_required
def telegram_users(request):
    """Telegram foydalanuvchilar ro'yxati"""
    telegram_users = TelegramUser.objects.all().order_by('-created_at')
    
    # Paginatsiya
    paginator = Paginator(telegram_users, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
    }
    return render(request, 'farm/admin_telegram_users.html', context)

# Barcha orderlar (admin uchun)
@staff_member_required
def all_orders(request):
    """Barcha orderlar (admin uchun)"""
    orders = Order.objects.all().order_by('-created_at')
    
    # Filtrlash
    status = request.GET.get('status')
    if status:
        orders = orders.filter(status=status)
    
    order_type = request.GET.get('type')
    if order_type:
        orders = orders.filter(order_type=order_type)
    
    # Paginatsiya
    paginator = Paginator(orders, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Statistikalar
    stats = {
        'total_orders': Order.objects.count(),
        'open_orders': Order.objects.filter(status='open').count(),
        'filled_orders': Order.objects.filter(status='filled').count(),
        'cancelled_orders': Order.objects.filter(status='cancelled').count(),
    }
    
    context = {
        'page_obj': page_obj,
        'stats': stats,
        'current_filters': {
            'status': status,
            'type': order_type,
        }
    }
    return render(request, 'farm/admin_all_orders.html', context)

# Barcha P2P orderlar (admin uchun)
@staff_member_required
def all_p2p_orders(request):
    """Barcha P2P orderlar (admin uchun)"""
    orders = P2POrder.objects.all().order_by('-created_at')
    
    # Filtrlash
    status = request.GET.get('status')
    if status:
        orders = orders.filter(status=status)
    
    # Paginatsiya
    paginator = Paginator(orders, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Statistikalar
    stats = {
        'total_orders': P2POrder.objects.count(),
        'open_orders': P2POrder.objects.filter(status=P2POrder.OPEN).count(),
        'filled_orders': P2POrder.objects.filter(status=P2POrder.FILLED).count(),
        'cancelled_orders': P2POrder.objects.filter(status=P2POrder.CANCELLED).count(),
    }
    
    context = {
        'page_obj': page_obj,
        'stats': stats,
        'current_filters': {
            'status': status,
        }
    }
    return render(request, 'farm/admin_all_p2p_orders.html', context)

# Barcha tranzaksiyalar (admin uchun)
@staff_member_required
def all_transactions(request):
    """Barcha tranzaksiyalar (admin uchun)"""
    transactions = Transaction.objects.all().order_by('-timestamp')
    
    # Filtrlash
    transaction_type = request.GET.get('type')
    if transaction_type:
        transactions = transactions.filter(type=transaction_type)
    
    currency = request.GET.get('currency')
    if currency:
        transactions = transactions.filter(currency=currency)
    
    # Paginatsiya
    paginator = Paginator(transactions, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Statistikalar
    stats = {
        'total_transactions': Transaction.objects.count(),
        'cf_transactions': Transaction.objects.filter(currency='CF').count(),
        'ton_transactions': Transaction.objects.filter(currency='TON').count(),
        'not_transactions': Transaction.objects.filter(currency='NOT').count(),
    }
    
    context = {
        'page_obj': page_obj,
        'stats': stats,
        'current_filters': {
            'type': transaction_type,
            'currency': currency,
        }
    }
    return render(request, 'farm/admin_all_transactions.html', context)
