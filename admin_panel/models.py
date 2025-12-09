from django.db import models
from decimal import Decimal
from django.utils import timezone

class TokenSupply(models.Model):
    """Модель для учета общего количества токенов в системе"""
    cf_total_supply = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0'))
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Общее количество токенов'
        verbose_name_plural = 'Общее количество токенов'
    
    @classmethod
    def get_current_supply(cls):
        """Получает текущее количество токенов в системе"""
        supply, created = cls.objects.get_or_create(id=1)
        return supply.cf_total_supply
    
    @classmethod
    def update_supply(cls, amount):
        """Обновить количество токенов в системе"""
        supply, created = cls.objects.get_or_create(id=1)
        supply.cf_total_supply += Decimal(amount)
        supply.save()
        return supply.cf_total_supply
    
    @classmethod
    def burn_tokens(cls, amount):
        """Сжигание токенов (уменьшение общего количества)"""
        supply, created = cls.objects.get_or_create(id=1)
        if supply.cf_total_supply >= Decimal(amount):
            supply.cf_total_supply -= Decimal(amount)
            supply.save()
            TokenOperation.objects.create(
                operation_type='burn',
                amount=amount,
                description=f'Сжигание {amount} CF токенов'
            )
            return True, supply.cf_total_supply
        return False, supply.cf_total_supply
    
    def __str__(self):
        return f'Общее количество CF токенов: {self.cf_total_supply}'

class TokenOperation(models.Model):
    """Модель для учета операций с токенами"""
    OPERATION_TYPES = [
        ('burn', 'Сжигание'),
        ('mint', 'Выпуск'),
        ('ton_distribution', 'Распределение TON'),
    ]
    
    operation_type = models.CharField(max_length=20, choices=OPERATION_TYPES)
    amount = models.DecimalField(max_digits=20, decimal_places=8)
    timestamp = models.DateTimeField(auto_now_add=True)
    description = models.TextField(blank=True)
    
    class Meta:
        verbose_name = 'Операция с токенами'
        verbose_name_plural = 'Операции с токенами'
        ordering = ['-timestamp']
    
    def __str__(self):
        return f'{self.get_operation_type_display()} - {self.amount} ({self.timestamp.strftime("%d.%m.%Y %H:%M")})'
