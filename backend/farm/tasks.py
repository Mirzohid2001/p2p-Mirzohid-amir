from celery import shared_task
from django.utils import timezone
from .models import Tree, Order, Staking, Transaction, SpecialTree, P2POrder, P2POrderCancelLog, User, WaterLog
from django.conf import settings
from telegram import Bot
from django.core.cache import cache
from decimal import Decimal
from .utils.notify import notify
import logging
from datetime import timedelta
from django.db import transaction
from django.contrib import messages
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

def _bot():
    """Telegram bot instance yaratish"""
    if hasattr(settings, 'TG_BOT_TOKEN') and settings.TG_BOT_TOKEN:
        return Bot(token=settings.TG_BOT_TOKEN)
    return None

def get_weekly_ad_income(kind):
    """Haftalik reklama daromadi"""
    return Decimal("100") if kind == SpecialTree.TON else Decimal("1000")

def send_web_notification(user, message, notification_type='info'):
    """Web notification yuborish (Django messages framework orqali)"""
    # Bu funksiya template'larda ko'rsatish uchun
    # Real vaqtda WebSocket yoki Server-Sent Events ishlatish mumkin
    logger.info(f"Web notification for user {user.id}: {message}")

@shared_task
def schedule_water_expiry(tree_id):
    """Poliv muddati tugaganda xabar yuborish"""
    try:
        tree = Tree.objects.get(id=tree_id)
        user = tree.owner
        now = timezone.now()

        # Free poliv muddati
        free_end = tree.last_watered + timedelta(hours=5) if tree.last_watered else None
        # Auto poliv muddati
        auto_end = tree.auto_water_expires

        free_expired = free_end and free_end <= now
        auto_expired = auto_end and auto_end <= now

        if free_expired or auto_expired:
            message = "🌱 Poliv to'xtadi! Daraxtni suvlang, coin ishlab chiqarishni faollashtirish uchun."
            
            # Telegram orqali xabar
            bot = _bot()
            if bot and user.tg_id:
                try:
                    bot.send_message(chat_id=user.tg_id, text=message)
                except Exception as e:
                    logger.error(f"Telegram xabar yuborishda xatolik: {e}")
            
            # Web notification
            send_web_notification(user, message, 'warning')
            
            # Email notification (agar email mavjud bo'lsa)
            if hasattr(user, 'email') and user.email:
                try:
                    send_mail(
                        'Crypto Farm - Poliv tugadi',
                        message,
                        settings.DEFAULT_FROM_EMAIL,
                        [user.email],
                        fail_silently=True,
                    )
                except Exception as e:
                    logger.error(f"Email yuborishda xatolik: {e}")
                    
    except Tree.DoesNotExist:
        logger.error(f"Tree {tree_id} topilmadi")
    except Exception as e:
        logger.error(f"schedule_water_expiry xatolik: {e}")

def _cancel_order(order):
    """Orderni bekor qilish"""
    with transaction.atomic():
        order.status = "cancelled"
        order.save(update_fields=["status"])

        # Pulni qaytarish
        if order.order_type == Order.SELL:
            order.seller.balance_cf += order.amount_cf
        else:
            ton_amount = (order.price_ton * order.amount_cf).quantize(Decimal("0.00000001"))
            order.seller.balance_ton += ton_amount
        
        order.seller.save()

        # Xabar yuborish
        message = f"⏰ Order #{order.id} muddati tugadi va bekor qilindi. Pul balansingizga qaytarildi."
        
        bot = _bot()
        if bot and order.seller.tg_id:
            try:
                bot.send_message(chat_id=order.seller.tg_id, text=message)
            except Exception as e:
                logger.error(f"Telegram xabar yuborishda xatolik: {e}")
        
        send_web_notification(order.seller, message, 'info')

@shared_task
def expire_order(order_id):
    """Orderning muddati tugaganda"""
    try:
        order = Order.objects.get(id=order_id, status="open")
        if order.expires_at <= timezone.now():
            _cancel_order(order)
            logger.info(f"Order {order_id} muddati tugadi")
    except Order.DoesNotExist:
        logger.warning(f"Order {order_id} topilmadi")
    except Exception as e:
        logger.error(f"expire_order xatolik: {e}")

@shared_task
def order_timeout():
    """Muddati tugagan orderlarni tekshirish"""
    now = timezone.now()
    expired_orders = Order.objects.filter(status='open', expires_at__lte=now)
    
    count = 0
    for order in expired_orders:
        try:
            _cancel_order(order)
            count += 1
        except Exception as e:
            logger.error(f"Order {order.id} bekor qilishda xatolik: {e}")
    
    if count > 0:
        logger.info(f"{count} ta order muddati tugadi va bekor qilindi")

@shared_task
def schedule_stake_complete(stake_id):
    """Staking tugaganda"""
    try:
        with transaction.atomic():
            stake = Staking.objects.select_for_update().get(id=stake_id, completed=False)
            
            # Staking tugadi
            stake.completed = True
            stake.save(update_fields=["completed"])

            # Bonus hisoblash
            bonus = stake.amount * (stake.bonus_percent / 100)
            stake.user.balance_cf += stake.amount + bonus  # Asosiy summa + bonus
            stake.user.save(update_fields=["balance_cf"])
            
            # Tranzaksiya yaratish
            Transaction.objects.create(
                user=stake.user,
                type='staking_complete',
                amount=stake.amount + bonus,
                currency='CF',
                description=f'Staking tugadi: {stake.bonus_percent}% bonus'
            )

            # Xabar yuborish
            message = f"🎉 Staking tugadi! {stake.bonus_percent}% bonus: {bonus:.8f} CF qo'shildi."
            
            bot = _bot()
            if bot and stake.user.tg_id:
                try:
                    bot.send_message(chat_id=stake.user.tg_id, text=message)
                except Exception as e:
                    logger.error(f"Telegram xabar yuborishda xatolik: {e}")
            
            send_web_notification(stake.user, message, 'success')
            
    except Staking.DoesNotExist:
        logger.warning(f"Staking {stake_id} topilmadi")
    except Exception as e:
        logger.error(f"schedule_stake_complete xatolik: {e}")

@shared_task
def distribute_ad_profit():
    """Haftalik reklama daromadini taqsimlash"""
    try:
        settings_value = cache.get_or_set("next_profit_kind", SpecialTree.TON)
        next_kind = SpecialTree.NOT if settings_value == SpecialTree.TON else SpecialTree.TON

        # Faol maxsus daraxtlar
        holders = (
            SpecialTree.objects
            .filter(
                kind=settings_value, 
                is_active=True,
                expires_at__gt=timezone.now()
            )
            .select_related("owner")
        )
        
        if not holders.exists():
            cache.set("next_profit_kind", next_kind)
            logger.info(f"Faol {settings_value} daraxtlar topilmadi")
            return

        total_profit = get_weekly_ad_income(settings_value)
        share = (total_profit / holders.count()).quantize(Decimal("0.00000001"))

        count = 0
        for special_tree in holders:
            try:
                with transaction.atomic():
                    user = User.objects.select_for_update().get(pk=special_tree.owner.pk)
                    
                    if settings_value == SpecialTree.TON:
                        user.balance_ton += share
                        currency = 'TON'
                    else:
                        user.balance_not += share
                        currency = 'NOT'
                    
                    user.save()
                    
                    # Tranzaksiya yaratish
                    Transaction.objects.create(
                        user=user,
                        type='ad_profit',
                        amount=share,
                        currency=currency,
                        description=f'Haftalik reklama daromadi: {special_tree.get_kind_display()}'
                    )
                    
                    # Xabar yuborish
                    message = f"🎁 Haftalik daromad: {share} {settings_value} qo'shildi!"
                    notify(user, message)
                    send_web_notification(user, message, 'success')
                    
                    count += 1
                    
            except Exception as e:
                logger.error(f"Ad profit taqsimlashda xatolik (user {special_tree.owner.id}): {e}")

        cache.set("next_profit_kind", next_kind)
        logger.info(f"{count} ta foydalanuvchiga {settings_value} daromadi taqsimlandi")
        
    except Exception as e:
        logger.error(f"distribute_ad_profit xatolik: {e}")

@shared_task
def log_commission_transfer(amount, order_id):
    """Komissiya o'tkazmasini loglash"""
    try:
        order = Order.objects.get(id=order_id)
        system_wallet = getattr(settings, 'SYSTEM_TON_WALLET', '')
        
        logger.info(
            f"Komissiya o'tkazmasi: {amount} TON order #{order_id} "
            f"dan tizim hamyoni {system_wallet} ga"
        )
        
        # Komissiya tranzaksiyasini yaratish
        Transaction.objects.create(
            user=order.seller,
            type='commission',
            amount=amount,
            currency='TON',
            description=f'Order #{order_id} komissiyasi'
        )
        
    except Order.DoesNotExist:
        logger.error(f"Order {order_id} topilmadi")
    except Exception as e:
        logger.error(f"Komissiya loglashda xatolik: {e}")

@shared_task
def deactivate_expired_special_trees():
    """Muddati tugagan maxsus daraxtlarni deaktivatsiya qilish"""
    try:
        now = timezone.now()
        expired_trees = SpecialTree.objects.filter(
            is_active=True, 
            expires_at__lt=now
        ).select_related("owner")
        
        count = 0
        for tree in expired_trees:
            try:
                tree.is_active = False
                tree.save(update_fields=["is_active"])
                
                # Xabar yuborish
                message = f"⚠️ {tree.get_kind_display()} muddati tugadi. Daromad olishni davom ettirish uchun yangilang."
                notify(tree.owner, message)
                send_web_notification(tree.owner, message, 'warning')
                
                count += 1
                
            except Exception as e:
                logger.error(f"Maxsus daraxt {tree.id} deaktivatsiya qilishda xatolik: {e}")
        
        if count > 0:
            logger.info(f"{count} ta maxsus daraxt deaktivatsiya qilindi")
            
    except Exception as e:
        logger.error(f"deactivate_expired_special_trees xatolik: {e}")

# Daraxt level bo'yicha daromad
LEVEL_YIELD = {
    1: Decimal('1'),
    2: Decimal('1.5'),
    3: Decimal('2'),
    4: Decimal('2.5'),
    5: Decimal('3'),
}

@shared_task
def distribute_passive_cf():
    """Passiv CF taqsimlash (har soat)"""
    try:
        now = timezone.now()
        five_hours_ago = now - timedelta(hours=5)

        # Free poliv bilan faol daraxtlar
        free_active = Tree.objects.filter(
            auto_water_expires__isnull=True,
            last_watered__gte=five_hours_ago
        ).select_related('owner', 'tree_type')

        # Auto poliv bilan faol daraxtlar
        auto_active = Tree.objects.filter(
            auto_water_expires__gt=now
        ).select_related('owner', 'tree_type')

        active_trees = free_active.union(auto_active)
        
        total_distributed = Decimal('0')
        user_count = 0

        for tree in active_trees:
            try:
                with transaction.atomic():
                    user = User.objects.select_for_update().get(pk=tree.owner.pk)
                    
                    # Daromad hisoblash
                    if tree.tree_type:
                        base = tree.tree_type.hourly_income
                    else:
                        base = LEVEL_YIELD.get(tree.level, Decimal(tree.level))
                    
                    # Fertilizer bonus
                    if tree.fertilizer_expires and tree.fertilizer_expires > now:
                        base *= 2

                    gain = base.quantize(Decimal('0.00000001'))

                    # Balansga qo'shish
                    user.balance_cf += gain
                    user.save(update_fields=['balance_cf'])
                    
                    # Water log yaratish
                    WaterLog.objects.create(
                        tree=tree,
                        type='passive',
                        amount=gain,
                        currency='CF'
                    )

                    # Tranzaksiya yaratish
                    Transaction.objects.create(
                        user=user,
                        type='passive_water',
                        amount=gain,
                        currency='CF',
                        description=f'Passiv daromad: Daraxt #{tree.id}'
                    )
                    
                    total_distributed += gain
                    user_count += 1
                    
            except Exception as e:
                logger.error(f"Passiv CF taqsimlashda xatolik (tree {tree.id}): {e}")

        logger.info(f"Passiv CF taqsimlandi: {total_distributed} CF, {user_count} ta foydalanuvchi")
        
    except Exception as e:
        logger.error(f"distribute_passive_cf xatolik: {e}")

@shared_task
def expire_p2p_order(order_id):
    """P2P order muddati tugaganda"""
    try:
        with transaction.atomic():
            order = P2POrder.objects.select_for_update().get(pk=order_id, status="open")
            user = User.objects.select_for_update().get(pk=order.seller.pk)
            
            # Pulni qaytarish
            user.balance_cf += order.amount_cf
            user.save(update_fields=["balance_cf"])
            
            # Log yaratish
            P2POrderCancelLog.objects.create(
                order=order,
                refunded_amount=order.amount_cf
            )
            
            # Status yangilash
            order.status = "expired"
            order.save(update_fields=["status"])
            
            # Tranzaksiya yaratish
            Transaction.objects.create(
                user=user, 
                type="p2p_expired_refund", 
                amount=order.amount_cf, 
                currency="CF",
                description=f'P2P order #{order_id} muddati tugadi'
            )
            
            # Xabar yuborish
            message = f"⏰ P2P order #{order_id} muddati tugadi. {order.amount_cf} CF qaytarildi."
            send_web_notification(user, message, 'info')
            
            logger.info(f"P2P Order #{order_id} muddati tugadi")
            
    except P2POrder.DoesNotExist:
        logger.warning(f"P2P Order #{order_id} topilmadi yoki ochiq emas")
    except Exception as e:
        logger.error(f"P2P order {order_id} muddati tugashida xatolik: {e}")

# Yangi task'lar Django template loyiha uchun

@shared_task
def send_daily_stats():
    """Kunlik statistikani yuborish"""
    try:
        from django.db.models import Sum, Count
        
        # Bugungi statistika
        today = timezone.now().date()
        today_start = timezone.datetime.combine(today, timezone.datetime.min.time())
        today_start = timezone.make_aware(today_start)
        
        stats = {
            'new_users': User.objects.filter(date_joined__gte=today_start).count(),
            'total_transactions': Transaction.objects.filter(timestamp__gte=today_start).count(),
            'cf_distributed': Transaction.objects.filter(
                timestamp__gte=today_start,
                currency='CF',
                type__in=['water', 'passive_water']
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0'),
            'orders_created': Order.objects.filter(created_at__gte=today_start).count(),
            'orders_filled': Order.objects.filter(
                created_at__gte=today_start,
                status='filled'
            ).count(),
        }
        
        logger.info(f"Kunlik statistika: {stats}")
        
        # Admin'larga email yuborish
        if hasattr(settings, 'ADMINS') and settings.ADMINS:
            admin_emails = [email for name, email in settings.ADMINS]
            message = f"""
Crypto Farm - Kunlik hisobot

Yangi foydalanuvchilar: {stats['new_users']}
Jami tranzaksiyalar: {stats['total_transactions']}
Taqsimlangan CF: {stats['cf_distributed']}
Yaratilgan orderlar: {stats['orders_created']}
Bajarilgan orderlar: {stats['orders_filled']}
            """
            
            try:
                send_mail(
                    'Crypto Farm - Kunlik hisobot',
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    admin_emails,
                    fail_silently=True,
                )
            except Exception as e:
                logger.error(f"Admin email yuborishda xatolik: {e}")
                
    except Exception as e:
        logger.error(f"send_daily_stats xatolik: {e}")

@shared_task
def cleanup_old_logs():
    """Eski loglarni tozalash"""
    try:
        # 30 kundan eski water loglarni o'chirish
        thirty_days_ago = timezone.now() - timedelta(days=30)
        
        old_water_logs = WaterLog.objects.filter(timestamp__lt=thirty_days_ago)
        count = old_water_logs.count()
        old_water_logs.delete()
        
        logger.info(f"{count} ta eski water log o'chirildi")
        
        # 90 kundan eski tranzaksiyalarni arxivlash (o'chirmasdan)
        # Bu yerda arxivlash logikasini qo'shish mumkin
        
    except Exception as e:
        logger.error(f"cleanup_old_logs xatolik: {e}")