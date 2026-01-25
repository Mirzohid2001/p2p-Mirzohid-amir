import random
from decimal import Decimal
from django.db import models
from django.utils import timezone

from users.models import User as TelegramUser

class Tree(models.Model):
    TYPE_CHOICES = (
        ('CF', 'FLORA'),
        ('TON', 'TON-Дерево'),
    )

    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="trees")
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='CF')
    level = models.PositiveSmallIntegerField(default=1)
    income_per_hour = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal('1.0'))
    branches_collected = models.PositiveIntegerField(default=0)
    last_cf_accrued = models.DateTimeField(null=True, blank=True)
    last_watered = models.DateTimeField(null=True, blank=True)
    fertilized_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    auto_water_until = models.DateTimeField(null=True, blank=True)
    last_collected = models.DateTimeField(null=True, blank=True)
    water_reminder_sent_at = models.DateTimeField(null=True, blank=True)

    BRANCH_DROP_CHANCE = 0.5
    WATER_DURATION = 5

    def is_watered(self):
        now = timezone.now()

        if self.auto_water_until and now < self.auto_water_until:
            return True

        if not self.last_watered:
            return False

        expiry = self.last_watered + timezone.timedelta(hours=self.WATER_DURATION)
        return now < expiry

    def is_fertilized(self):
        """Проверяем, не истёк ли эффект удобрения."""
        if not self.fertilized_until:
            return False
        return timezone.now() < self.fertilized_until

    def can_upgrade(self):
        from django.conf import settings
        next_level = self.level + 1
        levels = settings.GAME_SETTINGS.get("TREE_LEVELS", {})
        if next_level not in levels:
            return False
        required_branches = levels[next_level]["branches"]
        return self.user.branches_balance >= required_branches

    def upgrade(self):
        from django.conf import settings
        levels = settings.GAME_SETTINGS.get("TREE_LEVELS", {})
        next_level = self.level + 1
        if next_level not in levels:
            return False

        required_branches = levels[next_level]["branches"]
        if self.user.branches_balance < required_branches:
            return False

        # списываем ветки у пользователя
        self.user.branches_balance -= required_branches
        self.user.save(update_fields=["branches_balance"])

        # апаем дерево
        self.level = next_level

        # CF: меняем доход, TON: доход не обязателен (но можно оставить)
        if self.type == "CF":
            self.income_per_hour = Decimal(levels[next_level]["income"])
            self.save(update_fields=["level", "income_per_hour"])
        else:
            self.save(update_fields=["level"])

        return True

    def get_income_per_hour(self):
        now = timezone.now()
        if self.fertilized_until and now < self.fertilized_until:
            return self.income_per_hour * 2
        return self.income_per_hour

    def get_pending_income(self):
        """
        Считает, сколько CF или TON накопилось с последнего сбора (или полива, если не было сборов).
        CF — доход/ч, TON — 0.1*уровень за 5ч (пропорционально времени), оба учитывают удобрение.
        """
        from django.utils import timezone
        now = timezone.now()
        last_accrued = self.last_cf_accrued or self.last_watered
        if not last_accrued:
            return Decimal('0.0000')

        # Доход начисляется, пока есть вода (ручной полив или автополив)
        water_expiry = self.last_watered + timezone.timedelta(hours=self.WATER_DURATION) if self.last_watered else now
        # Если автополив действует — учитываем его окончание
        accrue_until = min(now,
                           self.auto_water_until) if self.auto_water_until and self.auto_water_until > now else min(now,
                                                                                                                    water_expiry)
        seconds_since = (accrue_until - last_accrued).total_seconds()
        hours = max(0, min(seconds_since / 3600, self.WATER_DURATION))

        # CF-дерево
        if self.type == "CF":
            income_per_hour = self.get_income_per_hour()
            pending_income = income_per_hour * Decimal(hours)
        # TON-дерево
        elif self.type == "TON":
            mult = Decimal("2") if self.is_fertilized() else Decimal("1")
            ton_per_hour = Decimal(self.level) * Decimal("0.01") * mult
            pending_income = ton_per_hour * Decimal(f"{hours:.10f}")

        else:
            pending_income = Decimal('0.0000')

        # Если нет активной раздачи — ничего не накапливаем!
        if self.type == "TON":
            from .models import TonDistribution
            active_dist = TonDistribution.objects.filter(is_active=True).last()
            if not active_dist:
                pending_income = Decimal('0.0000')
            else:
                # Нельзя собрать больше, чем осталось в пуле
                pending_income = min(pending_income, active_dist.left_to_distribute)
        return pending_income.quantize(Decimal('0.0000'))

    def get_water_percent(self):
        """
        Возвращает текущий процент воды (100% сразу после полива, линейно уменьшается до 0% за WATER_DURATION часов).
        """
        if not self.last_watered:
            return 0
        now = timezone.now()
        time_delta = now - self.last_watered
        hours_passed = min(time_delta.total_seconds() / 3600, self.WATER_DURATION)
        percent = max(0, 100 - int((hours_passed / self.WATER_DURATION) * 100))
        return percent

    def apply_shop_item(self, shop_item):
        now = timezone.now()
        if shop_item.type == 'fertilizer':
            hours = shop_item.duration or 24
            self.fertilized_until = now + timezone.timedelta(hours=hours)
            self.save(update_fields=["fertilized_until"])
            return "Дерево удобрено (доход х2)!"
        elif shop_item.type == 'auto_water':
            hours = shop_item.duration or 24
            self.auto_water_until = now + timezone.timedelta(hours=hours)
            self.save(update_fields=["auto_water_until"])
            return "Автополив активен!"

        return "Неизвестный предмет"

    def water(self):
        now = timezone.now()
        amount_cf = Decimal('0')
        amount_ton = Decimal('0')
        user = self.user

        # ✅ TON: запрещаем полив без активного пула
        if self.type == "TON":
            from .models import TonDistribution
            dist = TonDistribution.objects.filter(is_active=True).last()
            if not dist or dist.left_to_distribute <= 0:
                return {
                    "ok": False,
                    "message": "⛔ Раздача TON сейчас не активна или пул закончился.",
                    "branch_dropped": False,
                    "amount_cf": 0.0,
                    "amount_ton": 0.0,
                    "branches_collected": self.branches_collected,
                    "last_watered": self.last_watered.strftime("%d.%m.%Y %H:%M") if self.last_watered else "Никогда",
                    "pending_income": float(self.get_pending_income()),
                    "water_percent": self.get_water_percent(),
                }

        # ✅ CF: при поливе можно сразу начислить накопленное (как у тебя было)
        if self.type == "CF":
            amount_cf = self.get_pending_income()
            if amount_cf > 0:
                user.cf_balance += amount_cf
                user.save(update_fields=["cf_balance"])

        # 🌿 ветки (если хочешь — оставь только для CF)
        branch_dropped = False
        if self.type == "CF" and random.random() < self.BRANCH_DROP_CHANCE:
            branch_dropped = True
            user.branches_balance += 1
            user.save(update_fields=["branches_balance"])

        # обновляем воду
        self.last_watered = now
        self.water_reminder_sent_at = None
        self.save(update_fields=["last_watered", "water_reminder_sent_at"])

        return {
            "ok": True,
            "message": "Дерево успешно полито",
            "branch_dropped": branch_dropped,
            "amount_cf": float(amount_cf),
            "amount_ton": float(amount_ton),  # тут всегда 0, TON выдаётся через collect
            "branches_collected": self.branches_collected,
            "last_watered": now.strftime("%d.%m.%Y %H:%M"),
            "pending_income": float(self.get_pending_income()),
            "water_percent": self.get_water_percent(),
        }


class TonDistribution(models.Model):
    total_amount = models.DecimalField(max_digits=20, decimal_places=8,verbose_name="Всего TON")
    distributed_amount = models.DecimalField(max_digits=20, decimal_places=8, default=0,verbose_name="Распределено TON")
    is_active = models.BooleanField(default=True,verbose_name="Активна")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Раздача TON"
        verbose_name_plural = "Раздачи TON"

    @property
    def left_to_distribute(self):
        return self.total_amount - self.distributed_amount

    def accrue(self, user, tree):
        if not self.is_active:
            return Decimal('0')
        mult = Decimal("2") if tree.is_fertilized() else Decimal("1")
        max_per_water = (Decimal(tree.level) * Decimal("0.01") * Decimal(tree.WATER_DURATION) * mult)
        left = self.left_to_distribute
        amount = min(max_per_water, left)
        if amount > 0:
            user.ton_balance += amount
            user.save(update_fields=["ton_balance"])
            self.distributed_amount += amount
            self.save(update_fields=["distributed_amount"])
            if self.distributed_amount >= self.total_amount:
                self.is_active = False
                self.save(update_fields=["is_active"])
        return amount

    def __str__(self):
        return f"TON раздача #{self.id} — {self.total_amount} TON ({'активна' if self.is_active else 'завершена'})"


class BurnedToken(models.Model):
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    date = models.DateTimeField(auto_now_add=True)
    admin = models.ForeignKey('users.User', null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return f"Burned {self.amount} FL ({self.date:%Y-%m-%d %H:%M})"
