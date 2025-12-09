from rest_framework import serializers
from .models import User, Tree, WaterLog, UpgradeLog, Staking, Order, Transaction,SpecialTree,Donation,AdSlot,AdPurchase, P2POrder, TreeType, TreePurchaseTransaction
from django.conf import settings
from decimal import Decimal
from django.utils import timezone
from .services import is_watered, calculate_income

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id','tg_id','username','balance_cf','balance_ton','balance_not','referral_code','referred_by']

class TreeTypeSerializer(serializers.ModelSerializer):
    is_owned = serializers.SerializerMethodField()
    
    class Meta:
        model = TreeType
        fields = [
            'id',
            'name',
            'description',
            'price_ton',
            'hourly_income_multiplier',
            'is_default',
            'image_level_1',
            'image_level_2',
            'image_level_3',
            'created_at',
            'is_owned'
        ]
    
    def get_is_owned(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        
        # Проверяем, есть ли у пользователя дерево этого типа
        return Tree.objects.filter(owner=request.user, tree_type=obj).exists()

class TreePurchaseTransactionSerializer(serializers.ModelSerializer):
    tree_type = TreeTypeSerializer(read_only=True)
    tree_type_id = serializers.PrimaryKeyRelatedField(
        queryset=TreeType.objects.all(), write_only=True, source='tree_type'
    )
    
    class Meta:
        model = TreePurchaseTransaction
        fields = [
            'id',
            'user',
            'tree_type',
            'tree_type_id',
            'amount_ton',
            'transaction_hash',
            'status',
            'created_at',
            'completed_at'
        ]
        read_only_fields = ['user', 'amount_ton', 'transaction_hash', 'status', 'created_at', 'completed_at']

class TreeSerializer(serializers.ModelSerializer):
    total_branches = serializers.SerializerMethodField()
    is_watered = serializers.SerializerMethodField()
    hourly_income = serializers.SerializerMethodField()
    income_currency = serializers.SerializerMethodField()
    next_level_branches = serializers.SerializerMethodField()
    tree_type_details = TreeTypeSerializer(source='tree_type', read_only=True)
    total_earned = serializers.SerializerMethodField()
    can_use = serializers.SerializerMethodField()

    class Meta:
        model = Tree
        fields = [
            'id',
            'owner',
            'tree_type',
            'tree_type_details',
            'level',
            'last_watered',
            'auto_water_expires',
            'fertilizer_expires',
            'total_branches',
            'is_watered',
            'hourly_income',
            'income_currency',
            'next_level_branches',
            'total_earned',
            'can_use'
        ]

    def get_total_branches(self, obj):
        return sum(log.branches for log in obj.upgrade_logs.all())

    def get_is_watered(self, obj):
        return is_watered(obj)

    def get_hourly_income(self, obj):
        if not obj.tree_type:
            return 1.0  # Базовое дерево CF
        
        base_income = obj.tree_type.hourly_income
        if obj.fertilizer_expires and obj.fertilizer_expires > timezone.now():
            return float(base_income * 2)
        return float(base_income)

    def get_income_currency(self, obj):
        if not obj.tree_type:
            return 'CF'
        return obj.tree_type.income_currency

    def get_total_earned(self, obj):
        """Получаем общую сумму заработанную деревом"""
        currency = self.get_income_currency(obj)
        return sum(
            log.amount for log in obj.water_logs.filter(currency=currency)
        )

    def get_next_level_branches(self, obj):
        from .services import UPGRADE_REQ_BRANCH
        if obj.level >= 5:
            return None
        return UPGRADE_REQ_BRANCH.get(obj.level + 1)

    def get_can_use(self, obj):
        """Проверяет, может ли пользователь использовать это дерево"""
        # Если у дерева нет типа или оно бесплатное, его можно использовать
        if not obj.tree_type or obj.tree_type.price_ton == 0:
            return True
            
        # Проверяем, есть ли успешная транзакция покупки
        return TreePurchaseTransaction.objects.filter(
            user=obj.owner,
            tree_type=obj.tree_type,
            status="completed"
        ).exists()

class WaterLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = WaterLog
        fields = ['id','tree','type','timestamp']

class UpgradeLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = UpgradeLog
        fields = ['id','tree','branches','new_level','timestamp']

class StakingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Staking
        fields = ['id','user','started_at','duration_days','bonus_percent','completed']

class OrderSerializer(serializers.ModelSerializer):
    seller = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), required=False)

    class Meta:
        model = Order
        fields = ['id','seller','amount_cf','price_ton','order_type','status','created_at','expires_at']
        read_only_fields = ['status', 'created_at', 'expires_at', 'seller']

    def validate_amount_cf(self, value):
        if value <= 0:
            raise serializers.ValidationError('amount_cf must be greater than zero')
        return value

    def validate_price_ton(self, value):
        if value <= 0:
            raise serializers.ValidationError('price_ton must be greater than zero')

        # Проверка, что цена не превышает текущую цену CF
        current_price = Decimal(getattr(settings, 'CURRENT_CF_PRICE', 0.01))
        if value > current_price:
            raise serializers.ValidationError(f'price_ton cannot exceed current CF price: {current_price} TON')

        return value

class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = ['id','user','type','amount','currency','timestamp']


class SpecialTreeSerializer(serializers.ModelSerializer):
    days_left = serializers.SerializerMethodField()

    class Meta:
        model  = SpecialTree
        fields = ("id", "kind", "created_at", "expires_at", "is_active", "days_left")

    def get_days_left(self, obj):
        if not obj.expires_at:
            return None

        if obj.expires_at <= timezone.now():
            return 0

        days = (obj.expires_at - timezone.now()).days
        return days if days > 0 else 0

class DonationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Donation
        fields = ('id', 'amount_cf', 'created_at')

class AdSlotSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdSlot
        fields = ('id', 'name', 'price_cf', 'duration_h')

class AdPurchaseSerializer(serializers.ModelSerializer):
    slot = AdSlotSerializer(read_only=True)
    slot_id = serializers.PrimaryKeyRelatedField(
        queryset=AdSlot.objects.all(), source='slot', write_only=True
    )

    class Meta:
        model = AdPurchase
        fields = ('id', 'slot', 'slot_id', 'purchased_at', 'expires_at')


class UserProfileSerializer(serializers.ModelSerializer):
    referrals_count = serializers.SerializerMethodField()
    referral_earnings = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'balance_cf',
            'balance_ton',
            'balance_not',
            'referral_code',
            'referrals_count',
            'referral_earnings',
            'is_staff'
        ]
        read_only_fields = fields

    def get_referrals_count(self, obj):
        return obj.referrals.count()

    def get_referral_earnings(self, obj):
        from django.db.models import Sum
        from decimal import Decimal

        earnings = Transaction.objects.filter(
            user=obj,
            type="referral_reward"
        ).aggregate(total=Sum('amount', default=Decimal("0")))["total"]

        return earnings if earnings is not None else Decimal("0")

class ReferralCodeSerializer(serializers.Serializer):
    code = serializers.CharField(required=True, max_length=20)

class ReferralStatsSerializer(serializers.Serializer):
    referral_code = serializers.CharField()
    referrals_count = serializers.IntegerField()
    earnings = serializers.DecimalField(max_digits=20, decimal_places=8)
    referrals = serializers.ListField(child=serializers.DictField())

class ReferralResultSerializer(serializers.Serializer):
    inviter = serializers.CharField()
    bonus_invited = serializers.DecimalField(max_digits=20, decimal_places=8)
    bonus_inviter = serializers.DecimalField(max_digits=20, decimal_places=8)

class P2POrderSerializer(serializers.ModelSerializer):
    seller = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), required=False)
    buyer = serializers.PrimaryKeyRelatedField(read_only=True)
    profit_percent = serializers.SerializerMethodField()

    class Meta:
        model = P2POrder
        fields = ['id', 'seller', 'amount_cf', 'fixed_price_ton', 'current_market_price_ton',
                  'status', 'created_at', 'expires_at', 'filled_at', 'buyer', 'profit_percent']
        read_only_fields = ['status', 'created_at', 'expires_at', 'filled_at', 'buyer', 'current_market_price_ton']

    def validate_amount_cf(self, value):
        if value <= 0:
            raise serializers.ValidationError('amount_cf must be greater than zero')
        return value

    def validate_fixed_price_ton(self, value):
        if value <= 0:
            raise serializers.ValidationError('fixed_price_ton must be greater than zero')
        return value

    def get_profit_percent(self, obj):
        if obj.current_market_price_ton and obj.fixed_price_ton:
            profit = (obj.current_market_price_ton - obj.fixed_price_ton) / obj.fixed_price_ton * 100
            return round(profit, 2)
        return 0