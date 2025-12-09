from django.contrib import admin
from django.contrib.admin import helpers
from django.db.models import Sum, Count, Avg, Case, When, DecimalField, F
from django.db.models.functions import TruncDate
from django.utils.html import format_html
from django.utils import timezone
from django.urls import path
from django.template.response import TemplateResponse
from django.contrib import messages
from django.utils.safestring import mark_safe
from django.shortcuts import render
from decimal import Decimal, DecimalException

from .models import (
    User, Tree, WaterLog, UpgradeLog, Staking, Order, Transaction,
    SpecialTree, OrderCancelLog, Donation, AdSlot, AdPurchase,
    P2POrder, P2POrderCancelLog
)
from .tasks import get_weekly_ad_income

class UserAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'username', 'tg_id', 'balance_cf', 'balance_ton',
        'balance_not', 'referral_code'
    )
    search_fields = ('username', 'tg_id', 'referral_code')
    list_filter = ('is_staff', 'is_active', 'date_joined')
    
    actions = ['add_cf_balance', 'add_ton_balance', 'add_not_balance']
    
    def add_cf_balance(self, request, queryset):
        if 'apply' in request.POST:
            amount = request.POST.get('amount')
            description = request.POST.get('description', 'Добавление баланса через админ-панель')
            
            try:
                amount_decimal = Decimal(amount)
                updated = 0
                
                for user in queryset:
                    user.balance_cf += amount_decimal
                    user.save(update_fields=['balance_cf'])
                    
                    # Создаем транзакцию для учета
                    Transaction.objects.create(
                        user=user,
                        type='admin_adjustment',
                        amount=amount_decimal,
                        currency='CF',
                        description=description
                    )
                    updated += 1
                
                self.message_user(
                    request,
                    f'Успешно добавлено {amount} CF для {updated} пользователей.'
                )
                return None
                
            except (ValueError, DecimalException):
                self.message_user(
                    request,
                    'Пожалуйста, введите корректное число.',
                    level=messages.ERROR
                )
                return None
                
        context = {
            'title': 'Добавить CF баланс',
            'queryset': queryset,
            'action_checkbox_name': helpers.ACTION_CHECKBOX_NAME,
            'opts': self.model._meta
        }
        return render(request, 'admin/add_balance.html', context)
    
    add_cf_balance.short_description = 'Добавить CF баланс выбранным пользователям'
    
    def add_ton_balance(self, request, queryset):
        if 'apply' in request.POST:
            amount = request.POST.get('amount')
            description = request.POST.get('description', 'Добавление TON через админ-панель')
            
            try:
                amount_decimal = Decimal(amount)
                updated = 0
                
                for user in queryset:
                    user.balance_ton += amount_decimal
                    user.save(update_fields=['balance_ton'])
                    
                    # Создаем транзакцию для учета
                    Transaction.objects.create(
                        user=user,
                        type='admin_adjustment',
                        amount=amount_decimal,
                        currency='TON',
                        description=description
                    )
                    updated += 1
                
                self.message_user(
                    request,
                    f'Успешно добавлено {amount} TON для {updated} пользователей.'
                )
                return None
                
            except (ValueError, DecimalException):
                self.message_user(
                    request,
                    'Пожалуйста, введите корректное число.',
                    level=messages.ERROR
                )
                return None
                
        context = {
            'title': 'Добавить TON баланс',
            'queryset': queryset,
            'action_checkbox_name': helpers.ACTION_CHECKBOX_NAME,
            'opts': self.model._meta
        }
        return render(request, 'admin/add_balance.html', context)
    
    add_ton_balance.short_description = 'Добавить TON баланс выбранным пользователям'
    
    def add_not_balance(self, request, queryset):
        if 'apply' in request.POST:
            amount = request.POST.get('amount')
            description = request.POST.get('description', 'Добавление NOT через админ-панель')
            
            try:
                amount_decimal = Decimal(amount)
                updated = 0
                
                for user in queryset:
                    user.balance_not += amount_decimal
                    user.save(update_fields=['balance_not'])
                    
                    # Создаем транзакцию для учета
                    Transaction.objects.create(
                        user=user,
                        type='admin_adjustment',
                        amount=amount_decimal,
                        currency='NOT',
                        description=description
                    )
                    updated += 1
                
                self.message_user(
                    request,
                    f'Успешно добавлено {amount} NOT для {updated} пользователей.'
                )
                return None
                
            except (ValueError, DecimalException):
                self.message_user(
                    request,
                    'Пожалуйста, введите корректное число.',
                    level=messages.ERROR
                )
                return None
                
        context = {
            'title': 'Добавить NOT баланс',
            'queryset': queryset,
            'action_checkbox_name': helpers.ACTION_CHECKBOX_NAME,
            'opts': self.model._meta
        }
        return render(request, 'admin/add_balance.html', context)
    
    add_not_balance.short_description = 'Добавить NOT баланс выбранным пользователям'

class TreeAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'owner', 'level', 'last_watered',
        'auto_water_expires', 'fertilizer_expires'
    )
    list_filter = ('level', 'auto_water_expires', 'fertilizer_expires')
    search_fields = ('owner__username',)
    raw_id_fields = ('owner',)

class UpgradeLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'tree', 'branches', 'new_level', 'timestamp')
    list_filter = ('new_level', 'timestamp')
    date_hierarchy = 'timestamp'

class WaterLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'tree', 'type', 'timestamp')
    list_filter = ('type', 'timestamp')
    date_hierarchy = 'timestamp'

class StakingAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user', 'started_at', 'duration_days',
        'bonus_percent', 'completed', 'finishes_at'
    )
    list_filter = ('completed', 'duration_days', 'bonus_percent', 'started_at')
    search_fields = ('user__username',)
    raw_id_fields = ('user',)
    date_hierarchy = 'started_at'

class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'seller', 'amount_cf', 'price_ton',
        'order_type', 'status', 'created_at', 'expires_at'
    )
    list_filter = ('status', 'order_type', 'created_at', 'expires_at')
    search_fields = ('seller__username',)
    raw_id_fields = ('seller',)
    date_hierarchy = 'created_at'

class OrderCancelLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'cancelled_at', 'refunded_amount')
    list_filter = ('cancelled_at',)
    date_hierarchy = 'cancelled_at'

class TransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'type', 'amount', 'currency', 'timestamp')
    list_filter = ('type', 'currency', 'timestamp')
    search_fields = ('user__username',)
    raw_id_fields = ('user',)
    date_hierarchy = 'timestamp'

class SpecialTreeAdmin(admin.ModelAdmin):
    list_display = ('id', 'owner', 'kind', 'created_at')
    list_filter = ('kind', 'created_at')
    search_fields = ('owner__username',)
    raw_id_fields = ('owner',)
    date_hierarchy = 'created_at'

class DonationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'amount_cf', 'created_at')
    search_fields = ('user__username',)
    list_filter = ('created_at',)

class AdSlotAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'price_cf', 'duration_h')
    search_fields = ('name',)
    list_filter = ('price_cf', 'duration_h')

class AdPurchaseAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'slot', 'purchased_at', 'expires_at')
    raw_id_fields = ('user', 'slot')
    search_fields = ('user__username',)
    list_filter = ('purchased_at', 'expires_at')

class P2POrderAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'seller', 'buyer', 'amount_cf', 'fixed_price_ton', 
        'current_market_price_ton', 'profit_percentage', 'status', 'created_at'
    )
    list_filter = ('status', 'created_at', 'filled_at')
    search_fields = ('seller__username', 'buyer__username')
    raw_id_fields = ('seller', 'buyer')
    date_hierarchy = 'created_at'

    def profit_percentage(self, obj):
        if obj.current_market_price_ton and obj.fixed_price_ton:
            profit = (obj.current_market_price_ton - obj.fixed_price_ton) / obj.fixed_price_ton * 100
            color = 'green' if profit > 0 else 'red'
            profit_formatted = '{:.2f}%'.format(profit)
            return format_html('<span style="color:{}">{}</span>', color, profit_formatted)
        return '-'
    profit_percentage.short_description = 'Profit %'

class P2POrderCancelLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'cancelled_at', 'refunded_amount')
    list_filter = ('cancelled_at',)
    date_hierarchy = 'cancelled_at'
    raw_id_fields = ('order',)

class FarmAdminSite(admin.AdminSite):
    site_header = 'Crypto Farm Administration'
    site_title = 'Crypto Farm Admin'
    index_title = 'Farm Management'
    
    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            path('analytics/', self.admin_view(self.analytics_view), name='analytics'),
        ]
        return my_urls + urls
    
    def get_app_list(self, request):
        app_list = super().get_app_list(request)
        app_list.append({
            'name': 'Analytics',
            'app_label': 'analytics',
            'models': [{
                'name': 'Farm Analytics',
                'object_name': 'analytics',
                'admin_url': '/farm-admin/analytics/',
                'view_only': True,
            }],
        })
        return app_list
    
    def analytics_view(self, request):
        user_stats = {
            'total_users': User.objects.count(),
            'active_users': User.objects.filter(
                transactions__timestamp__gte=timezone.now() - timezone.timedelta(days=7)
            ).distinct().count(),
            'users_with_tg': User.objects.filter(tg_id__isnull=False).count(),
            'total_trees': Tree.objects.count(),
            'avg_tree_level': round(
                Tree.objects.aggregate(avg_level=Avg('level'))['avg_level'] or 0, 2
            ),
        }
        
        economy_stats = {
            'total_cf_balance': User.objects.aggregate(total=Sum('balance_cf'))['total'] or 0,
            'total_ton_balance': User.objects.aggregate(total=Sum('balance_ton'))['total'] or 0,
            'total_not_balance': User.objects.aggregate(total=Sum('balance_not'))['total'] or 0,
            'orders_open': Order.objects.filter(status='open').count(),
            'orders_filled': Order.objects.filter(status='filled').count(),
            'avg_order_price': Order.objects.filter(status='filled').aggregate(
                avg_price=Avg('price_ton')
            )['avg_price'] or 0,
            'total_commission': Transaction.objects.filter(
                type='commission'
            ).aggregate(total=Sum('amount'))['total'] or 0,
        }
        
        # P2P статистика
        p2p_stats = {
            'p2p_orders_open': P2POrder.objects.filter(status='open').count(),
            'p2p_orders_filled': P2POrder.objects.filter(status='filled').count(),
            'p2p_orders_cancelled': P2POrder.objects.filter(status='cancelled').count(),
            'p2p_orders_expired': P2POrder.objects.filter(status='expired').count(),
            'p2p_total_volume': P2POrder.objects.filter(status='filled').aggregate(
                total=Sum(F('amount_cf') * F('fixed_price_ton'))
            )['total'] or 0,
            'p2p_avg_price': P2POrder.objects.filter(status='filled').aggregate(
                avg=Avg('fixed_price_ton')
            )['avg'] or 0,
            'p2p_profit_opportunities': P2POrder.objects.filter(
                status='open', 
                fixed_price_ton__lt=F('current_market_price_ton')
            ).count(),
        }
        
        p2p_by_day = P2POrder.objects.filter(
            created_at__gte=timezone.now() - timezone.timedelta(days=7)
        ).annotate(
            date=TruncDate('created_at')
        ).values('date', 'status').annotate(
            count=Count('id'),
            cf_volume=Sum('amount_cf'),
            ton_volume=Sum(F('amount_cf') * F('fixed_price_ton'))
        ).order_by('date', 'status')
        
        ton_trees_count = SpecialTree.objects.filter(kind=SpecialTree.TON).count()
        not_trees_count = SpecialTree.objects.filter(kind=SpecialTree.NOT).count()
        special_tree_stats = {
            'ton_trees': ton_trees_count,
            'not_trees': not_trees_count,
            'ton_profit_per_tree': (
                get_weekly_ad_income(SpecialTree.TON) / max(ton_trees_count, 1)
            ),
            'not_profit_per_tree': (
                get_weekly_ad_income(SpecialTree.NOT) / max(not_trees_count, 1)
            ),
        }
        
        today = timezone.now().date()
        last_week = today - timezone.timedelta(days=7)
        
        transactions_by_day = Transaction.objects.filter(
            timestamp__gte=last_week
        ).values('currency').annotate(
            count=Count('id'),
            total=Sum('amount')
        )

        # Статистика по пассивному доходу (passive_water)
        passive_qs = Transaction.objects.filter(type='passive_water')
        total_passive = passive_qs.aggregate(total=Sum('amount'))['total'] or 0
        count_passive = passive_qs.count()
        passive_by_day = passive_qs.filter(
            timestamp__gte=last_week
        ).annotate(
            date=TruncDate('timestamp')
        ).values('date').annotate(
            daily_total=Sum('amount'),
            daily_count=Count('id')
        ).order_by('date')
        
        top_users = User.objects.annotate(
            transaction_count=Count('transactions')
        ).order_by('-transaction_count')[:5]
        top_users_data = [
            {
                'username': user.username,
                'transaction_count': user.transaction_count,
                'balance_cf': user.balance_cf,
                'balance_ton': user.balance_ton,
            } for user in top_users
        ]
        
        tree_levels = Tree.objects.values('level').annotate(
            count=Count('id')
        ).order_by('level')
        
        context = {
            **self.each_context(request),
            'title': 'Farm Analytics',
            'user_stats': user_stats,
            'economy_stats': economy_stats,
            'p2p_stats': p2p_stats,
            'p2p_by_day': list(p2p_by_day),
            'passive_water_stats': {
                'total_amount': total_passive,
                'transaction_count': count_passive,
                'by_day': list(passive_by_day),
            },
            'special_tree_stats': special_tree_stats,
            'transactions_by_day': transactions_by_day,
            'top_users': top_users_data,
            'tree_levels': tree_levels,
            'timestamp': timezone.now(),
        }
        return TemplateResponse(request, 'admin/analytics.html', context)

# Регистрация моделей на стандартном сайте
admin.site.register(User, UserAdmin)
admin.site.register(Tree, TreeAdmin)
admin.site.register(WaterLog, WaterLogAdmin)
admin.site.register(UpgradeLog, UpgradeLogAdmin)
admin.site.register(Staking, StakingAdmin)
admin.site.register(Order, OrderAdmin)
admin.site.register(OrderCancelLog, OrderCancelLogAdmin)
admin.site.register(Transaction, TransactionAdmin)
admin.site.register(SpecialTree, SpecialTreeAdmin)
admin.site.register(Donation, DonationAdmin)
admin.site.register(AdSlot, AdSlotAdmin)
admin.site.register(AdPurchase, AdPurchaseAdmin)
admin.site.register(P2POrder, P2POrderAdmin)
admin.site.register(P2POrderCancelLog, P2POrderCancelLogAdmin)

# Кастомная админка Farm
farm_admin_site = FarmAdminSite(name='farm_admin')
farm_admin_site.register(User, UserAdmin)
farm_admin_site.register(Tree, TreeAdmin)
farm_admin_site.register(WaterLog, WaterLogAdmin)
farm_admin_site.register(UpgradeLog, UpgradeLogAdmin)
farm_admin_site.register(Staking, StakingAdmin)
farm_admin_site.register(Order, OrderAdmin)
farm_admin_site.register(OrderCancelLog, OrderCancelLogAdmin)
farm_admin_site.register(Transaction, TransactionAdmin)
farm_admin_site.register(SpecialTree, SpecialTreeAdmin)
farm_admin_site.register(Donation, DonationAdmin)
farm_admin_site.register(AdSlot, AdSlotAdmin)
farm_admin_site.register(AdPurchase, AdPurchaseAdmin)
farm_admin_site.register(P2POrder, P2POrderAdmin)
farm_admin_site.register(P2POrderCancelLog, P2POrderCancelLogAdmin)
