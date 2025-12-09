from django.db import models
from django.utils import timezone
from users.models import User  # Используй свой путь к модели пользователя!

class PriceHistory(models.Model):
    date = models.DateField(unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f"{self.date}: {self.price}₽"

class Order(models.Model):
    ACTIONS = (
        ('buy', 'Купить CF за TON'),
        ('sell', 'Продать CF за TON')
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders')
    action = models.CharField(max_length=4, choices=ACTIONS)
    cf_amount = models.DecimalField(max_digits=15, decimal_places=2)
    price_rub = models.DecimalField(max_digits=15, decimal_places=2)
    ton_to_rub = models.DecimalField(max_digits=15, decimal_places=8)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    fulfilled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='fulfilled_orders')
    fulfilled_at = models.DateTimeField(null=True, blank=True)

    @property
    def price_in_ton(self):
        if self.ton_to_rub > 0:
            return round(float(self.price_rub) / float(self.ton_to_rub), 8)
        return 0

    def total_ton(self):
        return float(self.cf_amount) * float(self.price_in_ton)

    def __str__(self):
        return f"{self.get_action_display()} {self.cf_amount}CF @ {self.price_rub}₽"

class P2PSettings(models.Model):
    is_market_open = models.BooleanField(default=True)