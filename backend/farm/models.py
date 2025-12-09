from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
import random
import string
import logging


class User(AbstractUser):
    tg_id          = models.BigIntegerField(unique=True, null=True, blank=True)
    balance_cf     = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    balance_ton    = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    balance_not    = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    referral_code  = models.CharField(max_length=20, blank=True, null=True)
    referred_by    = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="referrals"
    )
    referrals_count = models.PositiveIntegerField(default=0)
    referral_earnings = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    photo_url = models.CharField(max_length=255, null=True, blank=True)
    auth_date = models.CharField(max_length=255, null=True, blank=True)
    username = models.CharField(max_length=150, unique=True)

    def __str__(self):
        return f"{self.username} ({self.id})"

    def save(self, *args, **kwargs):
        # Генерируем реферальный код для новых пользователей
        if not self.pk or not self.referral_code:
            # Генерируем уникальный реферальный код
            code_length = 8
            while True:
                code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=code_length))
                if not User.objects.filter(referral_code=code).exists():
                    break
            self.referral_code = code

        # Если это существующий пользователь, обновляем статистику рефералов
        if self.pk:
            self.update_referral_stats()

        super().save(*args, **kwargs)

        # Если изменился referred_by, обновляем статистику для реферера
        if self.referred_by:
            self.referred_by.update_referral_stats()
            self.referred_by.save()

    def update_referral_stats(self):
        """Обновляет статистику рефералов для пользователя"""
        from django.db.models import Sum
        from decimal import Decimal

        logger = logging.getLogger(__name__)
        logger.info(f"Обновление статистики рефералов для пользователя {self.username}")

        # Обновляем количество рефералов
        referrals_count = self.referrals.count()
        if self.referrals_count != referrals_count:
            self.referrals_count = referrals_count
            logger.info(f"Обновлено количество рефералов: {referrals_count}")

        # Обновляем заработок с рефералов
        earnings = Transaction.objects.filter(
            user=self,
            type="referral_reward",
            currency="CF"
        ).aggregate(total=Sum('amount'))["total"]

        if earnings is None:
            earnings = Decimal("0")

        if self.referral_earnings != earnings:
            self.referral_earnings = earnings
            logger.info(f"Обновлен заработок с рефералов: {earnings}")

        # Проверяем наличие транзакций для каждого реферала
        missing_referrals = 0
        for referral in self.referrals.all():
            # Проверяем, есть ли транзакция для этого реферала
            existing_transaction = Transaction.objects.filter(
                user=self,
                type="referral_reward",
                currency="CF",
                description__contains=referral.username
            ).first()

            # Если транзакции нет, создаем новую
            if not existing_transaction:
                from .services import REFERRAL_BONUS
                Transaction.objects.create(
                    user=self,
                    type="referral_reward",
                    amount=REFERRAL_BONUS,
                    currency="CF",
                    description=f"Бонус за приглашение пользователя {referral.username}"
                )

                # Обновляем баланс и заработок с рефералов
                self.balance_cf += REFERRAL_BONUS
                self.referral_earnings += REFERRAL_BONUS

                missing_referrals += 1
                logger.info(f"Создана транзакция для реферала {referral.username}")

        if missing_referrals > 0:
            logger.info(f"Создано {missing_referrals} транзакций для отсутствующих рефералов")

        return self.referrals_count, self.referral_earnings


class TreeType(models.Model):
    """Модель для разных типов деревьев"""
    CURRENCY_CHOICES = (
        ('CF', 'CryptoFlora'),
        ('TON', 'Toncoin'),
    )

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    price_ton = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    income_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='CF')
    hourly_income = models.DecimalField(max_digits=20, decimal_places=8, default=1.0)
    is_default = models.BooleanField(default=False)
    
    # Изображения для разных уровней
    image_level_1 = models.CharField(max_length=255, default='tree1.png')
    image_level_2 = models.CharField(max_length=255, default='tree2.png')
    image_level_3 = models.CharField(max_length=255, default='tree3.png')
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.income_currency})"

    def save(self, *args, **kwargs):
        # Если это первый тип дерева, сделаем его дефолтным
        if not TreeType.objects.exists():
            self.is_default = True
        # Если помечено как дефолтное, уберем этот флаг у всех остальных
        if self.is_default:
            TreeType.objects.exclude(id=self.id).update(is_default=False)
        super().save(*args, **kwargs)


class Tree(models.Model):
    owner               = models.ForeignKey(User, related_name="trees", on_delete=models.CASCADE)
    tree_type           = models.ForeignKey(TreeType, related_name="trees", on_delete=models.CASCADE, null=True)
    level               = models.PositiveSmallIntegerField(default=1)
    last_watered        = models.DateTimeField(null=True, blank=True)
    auto_water_expires  = models.DateTimeField(null=True, blank=True)
    fertilizer_expires  = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["owner"])]

    def __str__(self):
        return f"Tree#{self.id} type:{self.tree_type.name if self.tree_type else 'default'} lvl:{self.level} owner:{self.owner_id}"


class WaterLog(models.Model):
    WATER_TYPES = (
        ('free', 'Free'),
        ('auto', 'Auto'),
    )
    
    CURRENCY_CHOICES = (
        ('CF', 'CryptoFlora'),
        ('TON', 'Toncoin'),
    )
    
    tree = models.ForeignKey(Tree, on_delete=models.CASCADE, related_name='water_logs')
    type = models.CharField(max_length=10, choices=WATER_TYPES)
    timestamp = models.DateTimeField(auto_now_add=True)
    amount = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='CF')

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.tree_id} watered at {self.timestamp}"

class UpgradeLog(models.Model):
    tree        = models.ForeignKey(Tree, related_name="upgrade_logs", on_delete=models.CASCADE)
    branches    = models.PositiveIntegerField()
    new_level   = models.PositiveSmallIntegerField()
    timestamp   = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"UpgradeLog#{self.id} tree:{self.tree_id} branches:{self.branches} new_level:{self.new_level} timestamp:{self.timestamp}"


class Staking(models.Model):
    user            = models.ForeignKey(User, related_name="staking", on_delete=models.CASCADE)
    started_at      = models.DateTimeField(auto_now_add=True)
    duration_days   = models.PositiveSmallIntegerField(default=7)
    bonus_percent   = models.DecimalField(max_digits=5, decimal_places=2, default=10)
    completed       = models.BooleanField(default=False)

    @property
    def finishes_at(self):
        return self.started_at + timezone.timedelta(days=self.duration_days)


class Order(models.Model):
    SELL = "sell"
    BUY  = "buy"
    TYPE_CHOICES = [(SELL, "Sell"), (BUY, "Buy")]

    seller      = models.ForeignKey(User, related_name="sell_orders", on_delete=models.CASCADE)
    amount_cf   = models.DecimalField(max_digits=20, decimal_places=8)
    price_ton   = models.DecimalField(max_digits=20, decimal_places=8)
    order_type  = models.CharField(max_length=4, choices=TYPE_CHOICES, default=SELL)
    status      = models.CharField(max_length=10, default="open")
    created_at  = models.DateTimeField(auto_now_add=True)
    expires_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["order_type"]),
            models.Index(fields=["expires_at"]),
        ]

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(days=3)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Order#{self.id} {self.order_type.upper()} {self.amount_cf}CF @ {self.price_ton}TON ({self.status})"

class OrderCancelLog(models.Model):
    order           = models.OneToOneField(Order, related_name="cancel_log", on_delete=models.CASCADE)
    cancelled_at    = models.DateTimeField(auto_now_add=True)
    refunded_amount = models.DecimalField(max_digits=20, decimal_places=8, editable=False)

    def save(self, *args, **kwargs):
        self.refunded_amount = self.order.amount_cf
        super().save(*args, **kwargs)


class Transaction(models.Model):
    user      = models.ForeignKey(User, related_name="transactions", on_delete=models.CASCADE)
    type      = models.CharField(max_length=20)
    amount    = models.DecimalField(max_digits=20, decimal_places=8)
    currency  = models.CharField(max_length=4, choices=[("CF", "CF"), ("TON", "TON"), ("NOT", "NOT")])
    timestamp = models.DateTimeField(auto_now_add=True)
    description = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        ordering = ("-timestamp",)


class SpecialTree(models.Model):
    TON  = "TON"
    NOT  = "NOT"
    KIND_CHOICES = [(TON, "TON‑tree"), (NOT, "NOT‑tree")]

    owner      = models.ForeignKey(User, related_name="special_trees", on_delete=models.CASCADE)
    kind       = models.CharField(max_length=3, choices=KIND_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active  = models.BooleanField(default=True)

    class Meta:
        unique_together = ("owner", "kind")

    def __str__(self):
        return f"{self.kind}-tree owner:{self.owner_id}"

    def save(self, *args, **kwargs):
        if not self.expires_at and not self.id:
            self.expires_at = timezone.now() + timezone.timedelta(days=30)
        super().save(*args, **kwargs)


class Donation(models.Model):
    user = models.ForeignKey(
        'User', on_delete=models.CASCADE, related_name='donations'
    )
    amount_cf = models.DecimalField(max_digits=20, decimal_places=8)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Donation#{self.id} {self.amount_cf} CF by {self.user.username}"


class AdSlot(models.Model):
    name = models.CharField(max_length=50)
    price_cf = models.DecimalField(max_digits=20, decimal_places=8)
    duration_h = models.PositiveIntegerField()

    def __str__(self):
        return f"AdSlot {self.name}: {self.price_cf} CF for {self.duration_h}h"


class AdPurchase(models.Model):
    user = models.ForeignKey(
        'User', on_delete=models.CASCADE, related_name='ad_purchases'
    )
    slot = models.ForeignKey(
        AdSlot, on_delete=models.CASCADE, related_name='purchases'
    )
    purchased_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def __str__(self):
        return f"AdPurchase#{self.id} slot:{self.slot.name} by {self.user.username}"


class P2POrder(models.Model):
    OPEN = "open"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"

    STATUS_CHOICES = [
        (OPEN, "Open"),
        (FILLED, "Filled"),
        (CANCELLED, "Cancelled"),
        (EXPIRED, "Expired")
    ]

    seller = models.ForeignKey(User, related_name="p2p_orders", on_delete=models.CASCADE)
    amount_cf = models.DecimalField(max_digits=20, decimal_places=8)
    fixed_price_ton = models.DecimalField(max_digits=20, decimal_places=8)
    current_market_price_ton = models.DecimalField(max_digits=20, decimal_places=8)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    filled_at = models.DateTimeField(null=True, blank=True)
    buyer = models.ForeignKey(User, related_name="p2p_purchases", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["expires_at"]),
        ]

    def save(self, *args, **kwargs):
        # Для новых ордеров устанавливаем срок действия на 3 дня вперед
        if not self.id:
            self.expires_at = timezone.now() + timezone.timedelta(days=3)
        
        # Дополнительная проверка для существующих ордеров
        # Если срок истек и статус все еще "открыт", меняем на "истек"
        elif self.status == self.OPEN and self.expires_at and self.expires_at <= timezone.now():
            self.status = self.EXPIRED

        # Обновляем expires_at, если он явно не установлен
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(days=3)
            
        super().save(*args, **kwargs)

    def __str__(self):
        return f"P2POrder#{self.id} {self.amount_cf}CF @ fixed:{self.fixed_price_ton}TON (market:{self.current_market_price_ton}TON) ({self.status})"

class P2POrderCancelLog(models.Model):
    order = models.OneToOneField(P2POrder, related_name="cancel_log", on_delete=models.CASCADE)
    cancelled_at = models.DateTimeField(auto_now_add=True)
    refunded_amount = models.DecimalField(max_digits=20, decimal_places=8, editable=False)

    def save(self, *args, **kwargs):
        self.refunded_amount = self.order.amount_cf
        super().save(*args, **kwargs)


class TelegramUser(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='telegram_data')
    chat_id = models.CharField(max_length=255, unique=True)
    photo_url = models.CharField(max_length=255, null=True, blank=True)
    auth_date = models.CharField(max_length=255)
    hash = models.CharField(max_length=255)
    username = models.CharField(max_length=255, null=True, blank=True)
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = 'telegram_users'

    def __str__(self):
        return f"{self.username} ({self.chat_id})"


class TreePurchaseTransaction(models.Model):
    """Модель для отслеживания покупки новых типов деревьев за TON"""
    user = models.ForeignKey(User, related_name="tree_purchases", on_delete=models.CASCADE)
    tree_type = models.ForeignKey(TreeType, on_delete=models.CASCADE)
    amount_ton = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_hash = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(
        max_length=20, 
        choices=[
            ("pending", "Pending"), 
            ("completed", "Completed"), 
            ("failed", "Failed")
        ],
        default="pending"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"Purchase of {self.tree_type.name} for {self.amount_ton} TON by {self.user.username} ({self.status})"






