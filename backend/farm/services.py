# apps/core/services.py
import random
import string
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from django.conf import settings
from .models import Tree, WaterLog, UpgradeLog, Transaction, Staking, SpecialTree, User, TreeType, TreePurchaseTransaction
from .tasks import schedule_water_expiry, schedule_stake_complete
from .utils.notify import notify
from django.db.models import Sum
import logging
from django.db import transaction

AUTO_WATER_PRICES   = {24: 50, 48: 90, 72: 120}
FERTILIZER_PRICES   = {1: 24, 2: 36, 3: 48, 4: 60, 5: 72}
UPGRADE_REQ_BRANCH  = {2: 5, 3: 12, 4: 30, 5: 75}
WATER_COOLDOWN = 4  # Время в часах между поливами

# Константы для реферальной системы
REFERRAL_CODE_LENGTH = 8  # Длина реферального кода
REFERRAL_BONUS = Decimal("50.0")  # Бонус 50 CF и приглашающему и приглашенному

# Доход с разных уровней дерева
LEVEL_INCOME = {
    1: Decimal("1.0"),
    2: Decimal("1.5"),
    3: Decimal("2.0"),
    4: Decimal("2.5"),
    5: Decimal("3.0")
}

# Время полива в часах
WATER_DURATION = 5

def calculate_income(tree: Tree) -> Decimal:
    """Рассчитывает базовый доход дерева за час"""
    base_income = LEVEL_INCOME.get(tree.level, Decimal("1.0"))
    if tree.fertilizer_expires and tree.fertilizer_expires > timezone.now():
        return (base_income * Decimal("2")).quantize(Decimal("0.00000001"))
    return base_income.quantize(Decimal("0.00000001"))

def is_watered(tree: Tree) -> bool:
    """Проверяет, действует ли ещё полив дерева"""
    if not tree.last_watered:
        return False

    now = timezone.now()
    if tree.auto_water_expires and tree.auto_water_expires > now:
        return True

    water_time = now - tree.last_watered
    return water_time.total_seconds() <= WATER_DURATION * 3600

def try_drop_branch(tree: Tree) -> bool:
    """Пытается добавить ветку с 10% шансом"""
    total_branches = sum(log.branches for log in tree.upgrade_logs.all())
    if total_branches >= 75:
        return False

    if random.random() < 0.1:  # 10% шанс
        UpgradeLog.objects.create(
            tree=tree,
            branches=1,
            new_level=tree.level
        )
        return True
    return False

def water_tree(tree: Tree, user):
    """
    Поливает дерево и начисляет награду
    Возвращает количество полученных монет и их тип
    """
    now = timezone.now()

    # Проверяем, не действует ли ещё предыдущий полив
    if is_watered(tree):
        raise ValueError("Дерево уже полито")

    tree.last_watered = now
    tree.save(update_fields=["last_watered"])

    # Определяем тип валюты и базовый доход
    if tree.tree_type:
        currency = tree.tree_type.income_currency
        base_income = tree.tree_type.hourly_income
    else:
        currency = 'CF'
        base_income = Decimal('1.0')

    # Рассчитываем доход с учетом удобрения
    if tree.fertilizer_expires and tree.fertilizer_expires > now:
        gain = base_income * 2
    else:
        gain = base_income

    # Начисляем монеты в зависимости от типа
    if currency == 'CF':
        user.balance_cf += gain
        user.save(update_fields=["balance_cf"])
    elif currency == 'TON':
        user.balance_ton += gain
        user.save(update_fields=["balance_ton"])

    # Логируем полив
    WaterLog.objects.create(
        tree=tree,
        type="free",
        amount=gain,
        currency=currency
    )

    # Создаём транзакцию
    Transaction.objects.create(
        user=user,
        type="water",
        amount=gain,
        currency=currency
    )

    # Пробуем получить ветку
    branch_dropped = try_drop_branch(tree)

    # Отправляем уведомление
    message = f"💧 Полив дерева принёс вам {gain} {currency}!"
    if branch_dropped:
        message += "\n🌿 Вы нашли ветку!"
    notify(user, message)

    # Планируем проверку окончания полива
    schedule_water_expiry.apply_async(
        (tree.id,),
        eta=now + timedelta(hours=WATER_DURATION)
    )

    return {
        'amount': gain,
        'currency': currency
    }


def auto_water_tree(tree: Tree, user, hours: int):
    if hours not in AUTO_WATER_PRICES:
        raise ValueError("Неверный срок авто‑полива")
    price = Decimal(AUTO_WATER_PRICES[hours]).quantize(Decimal("0.00000001"))

    if user.balance_cf < price:
        raise ValueError("Недостаточно CF")
    user.balance_cf -= price
    user.save(update_fields=["balance_cf"])

    tree.auto_water_expires = timezone.now() + timedelta(hours=hours)
    tree.save(update_fields=["auto_water_expires"])

    Transaction.objects.create(user=user, type="auto_water", amount=price, currency="CF")
    return price


def fertilize_tree(tree: Tree, user):
    price = Decimal(FERTILIZER_PRICES.get(tree.level, 24)).quantize(Decimal("0.00000001"))
    if user.balance_cf < price:
        raise ValueError("Недостаточно CF")
    user.balance_cf -= price
    user.save(update_fields=["balance_cf"])

    tree.fertilizer_expires = timezone.now() + timedelta(hours=24)
    tree.save(update_fields=["fertilizer_expires"])

    Transaction.objects.create(user=user, type="fertilize", amount=price, currency="CF")
    return price

def upgrade_tree(tree: Tree) -> bool:
    """
    Пытается улучшить дерево, если достаточно веток
    Возвращает True если улучшение успешно, False если нет
    """
    if tree.level >= 5:
        return False

    next_level = tree.level + 1
    required_branches = UPGRADE_REQ_BRANCH.get(next_level)

    if not required_branches:
        return False

    total_branches = sum(log.branches for log in tree.upgrade_logs.all())

    if total_branches < required_branches:
        return False

    tree.level = next_level
    tree.save(update_fields=["level"])

    notify(tree.owner, f"🌳 Ваше дерево достигло {next_level} уровня!")

    return True


def create_staking(user, amount_cf, days=7, bonus_percent=10):
    # Проверяем и квантуем значения
    amount_cf = Decimal(amount_cf).quantize(Decimal("0.00000001"))

    if user.balance_cf < amount_cf:
        raise ValueError("Недостаточно CF для стейкинга")
    user.balance_cf -= Decimal(amount_cf)
    user.save(update_fields=["balance_cf"])

    stake = Staking.objects.create(
        user=user,
        duration_days=days,
        bonus_percent=Decimal(bonus_percent).quantize(Decimal("0.01"))
    )

    schedule_stake_complete.apply_async((stake.id,), eta=stake.finishes_at)
    return stake

TON_TREE_PRICE_TON  = Decimal("1")
NOT_TREE_PRICE_NOT  = Decimal("1000")

def buy_special_tree(user, kind: str):
    # Проверяем, есть ли уже активное дерево этого типа
    existing_tree = SpecialTree.objects.filter(
        owner=user,
        kind=kind,
        is_active=True,
        expires_at__gt=timezone.now()
    ).first()

    # Если есть активное дерево, продлеваем его срок действия
    if existing_tree:
        if kind == SpecialTree.TON:
            if user.balance_ton < TON_TREE_PRICE_TON:
                raise ValueError("Недостаточно TON.")
            user.balance_ton -= TON_TREE_PRICE_TON
            currency, amount = "TON", TON_TREE_PRICE_TON
        elif kind == SpecialTree.NOT:
            if user.balance_not < NOT_TREE_PRICE_NOT:
                raise ValueError("Недостаточно NOT.")
            user.balance_not -= NOT_TREE_PRICE_NOT
            currency, amount = "NOT", NOT_TREE_PRICE_NOT
        else:
            raise ValueError("Неверный тип дерева.")

        # Продлеваем срок действия на 30 дней от текущей даты истечения
        if existing_tree.expires_at:
            existing_tree.expires_at = existing_tree.expires_at + timezone.timedelta(days=30)
        else:
            existing_tree.expires_at = timezone.now() + timezone.timedelta(days=30)

        existing_tree.save(update_fields=["expires_at"])
        user.save(update_fields=[f"balance_{currency.lower()}"])

        Transaction.objects.create(
            user=user, type=f"extend_{kind.lower()}_tree", amount=amount, currency=currency
        )
        return existing_tree

    # Если нет активного дерева, создаем новое
    if kind == SpecialTree.TON:
        if user.balance_ton < TON_TREE_PRICE_TON:
            raise ValueError("Недостаточно TON.")
        user.balance_ton -= TON_TREE_PRICE_TON
        currency, amount = "TON", TON_TREE_PRICE_TON
    elif kind == SpecialTree.NOT:
        if user.balance_not < NOT_TREE_PRICE_NOT:
            raise ValueError("Недостаточно NOT.")
        user.balance_not -= NOT_TREE_PRICE_NOT
        currency, amount = "NOT", NOT_TREE_PRICE_NOT
    else:
        raise ValueError("Неверный тип дерева.")

    user.save(update_fields=[f"balance_{currency.lower()}"])

    # Создаем новое дерево
    special = SpecialTree.objects.create(
        owner=user,
        kind=kind,
        is_active=True,
        expires_at=timezone.now() + timezone.timedelta(days=30)
    )

    Transaction.objects.create(
        user=user, type=f"buy_{kind.lower()}_tree", amount=amount, currency=currency
    )
    return special

def generate_referral_code(user):
    """
    Генерирует уникальный реферальный код для пользователя
    или возвращает существующий
    """
    # Если у пользователя уже есть код, возвращаем его
    if user.referral_code:
        return user.referral_code

    # Генерируем новый уникальный код
    tries = 0
    while tries < 10:  # Ограничиваем количество попыток
        tries += 1
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=REFERRAL_CODE_LENGTH))
        if not User.objects.filter(referral_code=code).exists():
            user.referral_code = code
            user.save(update_fields=["referral_code"])
            return code

    # Если не смогли сгенерировать уникальный код за 10 попыток,
    # добавляем к базовому коду ID пользователя для уникальности
    backup_code = f"{''.join(random.choices(string.ascii_uppercase, k=4))}{user.id}"
    user.referral_code = backup_code
    user.save(update_fields=["referral_code"])
    return backup_code

def apply_referral_code(user, code):
    """
    Применяет реферальный код и начисляет бонусы
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Пользователь {user.username} пытается применить код {code}")

    # Проверяем, что пользователь ещё не использовал реферальный код
    if user.referred_by:
        logger.warning(f"Пользователь {user.username} уже использовал реферальный код")
        raise ValueError("Вы уже использовали реферальный код")

    # Находим пользователя по коду
    inviter = User.objects.filter(referral_code=code).first()
    if not inviter:
        logger.warning(f"Пользователь {user.username} пытается использовать несуществующий код {code}")
        raise ValueError("Неверный реферальный код")

    # Проверяем, что пользователь не пытается использовать свой код
    if inviter.id == user.id:
        logger.warning(f"Пользователь {user.username} пытается использовать свой код")
        raise ValueError("Нельзя использовать свой реферальный код")

    # Устанавливаем связь и начисляем бонусы
    user.referred_by = inviter
    user.balance_cf += REFERRAL_BONUS  # 50 CF приглашенному
    user.save(update_fields=["referred_by", "balance_cf"])

    # Обновляем статистику инвайтера
    inviter.referrals_count = inviter.referrals.count()
    inviter.balance_cf += REFERRAL_BONUS  # 50 CF пригласившему
    inviter.referral_earnings = (inviter.referral_earnings or 0) + REFERRAL_BONUS
    inviter.save(update_fields=["balance_cf", "referrals_count", "referral_earnings"])

    # Создаём транзакции
    try:
        Transaction.objects.create(
            user=user,
            type="referral_bonus",
            amount=REFERRAL_BONUS,
            currency="CF",
            description="Бонус за использование реферального кода"
        )

        Transaction.objects.create(
            user=inviter,
            type="referral_reward",
            amount=REFERRAL_BONUS,
            currency="CF",
            description=f"Бонус за приглашение пользователя {user.username}"
        )

        logger.info(f"Успешно созданы транзакции для пользователя {user.username} и инвайтера {inviter.username}")
    except Exception as e:
        logger.error(f"Ошибка при создании транзакций: {str(e)}")

    # Отправляем уведомления
    notify(user, f"🎁 Вы получили бонус {REFERRAL_BONUS} CF за использование реферального кода!")
    notify(inviter, f"👥 Пользователь {user.username} использовал ваш реферальный код! Вы получили {REFERRAL_BONUS} CF.")

    return {
        "inviter": inviter.username,
        "bonus_invited": REFERRAL_BONUS,
        "bonus_inviter": REFERRAL_BONUS
    }

def get_referral_stats(user):
    """
    Получает статистику по рефералам пользователя
    """
    from django.db.models import Sum
    from decimal import Decimal

    logger = logging.getLogger(__name__)
    logger.info(f"Получение статистики рефералов для пользователя {user.username}")

    # Если у пользователя нет реферального кода, генерируем его
    if not user.referral_code:
        generate_referral_code(user)

    # Получаем рефералов
    referrals = user.referrals.all()
    referrals_count = referrals.count()
    logger.info(f"Количество рефералов: {referrals_count}")

    # Обновляем количество рефералов в модели пользователя
    if user.referrals_count != referrals_count:
        user.referrals_count = referrals_count
        user.save(update_fields=['referrals_count'])
        logger.info(f"Обновлено количество рефералов: {referrals_count}")

    # Проверяем, есть ли транзакции типа "referral_reward" для каждого реферала
    fixed_count = fix_missing_referral_transactions(user, referrals)
    if fixed_count > 0:
        logger.info(f"Исправлено {fixed_count} отсутствующих транзакций для рефералов")

    # Получаем заработок с рефералов
    try:
        earnings = Transaction.objects.filter(
            user=user,
            type="referral_reward",
            currency="CF"
        ).aggregate(total=Sum('amount'))["total"] or Decimal("0")

        logger.info(f"Рассчитанный заработок с рефералов: {earnings}")

        # Обновляем заработок с рефералов в модели пользователя
        if user.referral_earnings != earnings:
            user.referral_earnings = earnings
            user.save(update_fields=['referral_earnings'])
            logger.info(f"Обновлен заработок с рефералов: {earnings}")
    except Exception as e:
        logger.error(f"Ошибка при расчете заработка с рефералов: {str(e)}")
        earnings = user.referral_earnings

    # Получаем детальную информацию о рефералах
    referral_details = []
    try:
        for ref in referrals:
            try:
                ref_earnings = Transaction.objects.filter(
                    user=user,
                    type="referral_reward",
                    currency="CF",
                    description__contains=ref.username
                ).aggregate(total=Sum('amount'))["total"] or Decimal("0")

                referral_details.append({
                    "username": ref.username,
                    "date_joined": ref.date_joined,
                    "total_earnings": ref_earnings
                })
            except Exception as e:
                logger.error(f"Ошибка при получении данных о реферале {ref.username}: {str(e)}")
                referral_details.append({
                    "username": ref.username,
                    "date_joined": ref.date_joined,
                    "total_earnings": Decimal("0")
                })
    except Exception as e:
        logger.error(f"Ошибка при сборе деталей о рефералах: {str(e)}")

    stats = {
        "referral_code": user.referral_code or "",
        "referrals_count": referrals_count,
        "earnings": earnings,
        "referrals": referral_details
    }
    logger.info(f"Итоговая статистика: {stats}")
    return stats

def fix_missing_referral_transactions(user, referrals=None):
    """
    Добавляет недостающие транзакции для рефералов, добавленных вручную через админку
    """
    total_missing_earnings = Decimal("0")
    fixed_referrals = 0

    if referrals is None:
        referrals = user.referrals.all()

    for referral in referrals:
        # Проверяем, есть ли уже транзакция для этого реферала
        existing_transaction = Transaction.objects.filter(
            user=user,
            type="referral_reward",
            currency="CF",
            description__contains=referral.username
        ).first()

        # Если транзакции нет, создаем новую
        if not existing_transaction:
            Transaction.objects.create(
                user=user,
                type="referral_reward",
                amount=REFERRAL_BONUS,
                currency="CF",
                description=f"Бонус за приглашение пользователя {referral.username}"
            )

            # Обновляем заработок с рефералов
            total_missing_earnings += REFERRAL_BONUS
            fixed_referrals += 1

    # Если были добавлены транзакции, обновляем пользователя
    if fixed_referrals > 0:
        # Обновляем баланс пользователя
        user.balance_cf += total_missing_earnings
        user.referral_earnings += total_missing_earnings
        user.save(update_fields=["balance_cf", "referral_earnings"])

        # Логирование для отладки
        print(f"Исправлено {fixed_referrals} рефералов, добавлено {total_missing_earnings} CF для {user.username}")

    return fixed_referrals

def get_available_tree_types(user):
    """Получает список доступных типов деревьев для пользователя"""
    tree_types = TreeType.objects.all()
    result = []
    
    for tree_type in tree_types:
        is_owned = Tree.objects.filter(owner=user, tree_type=tree_type).exists()
        result.append({
            'id': tree_type.id,
            'name': tree_type.name,
            'description': tree_type.description,
            'price_ton': float(tree_type.price_ton),
            'hourly_income_multiplier': float(tree_type.hourly_income_multiplier),
            'is_default': tree_type.is_default,
            'is_owned': is_owned,
            'image_level_1': tree_type.image_level_1,
            'image_level_2': tree_type.image_level_2,
            'image_level_3': tree_type.image_level_3
        })
    
    return result

def purchase_tree_type(user, tree_type_id, transaction_hash=None):
    """Покупка нового типа дерева"""
    with transaction.atomic():
        tree_type = TreeType.objects.get(id=tree_type_id)
        
        # Проверяем, есть ли уже такое дерево у пользователя
        if Tree.objects.filter(owner=user, tree_type=tree_type).exists():
            raise ValueError("У вас уже есть дерево этого типа")
        
        # Если это бесплатное дерево, просто создаем его
        if tree_type.price_ton == 0:
            tree = Tree.objects.create(
                owner=user,
                tree_type=tree_type,
                level=1
            )
            return tree
        
        # Для платных деревьев проверяем транзакцию
        if not transaction_hash:
            raise ValueError("Требуется подтверждение оплаты")
        
        # Создаем запись о покупке
        purchase = TreePurchaseTransaction.objects.create(
            user=user,
            tree_type=tree_type,
            amount_ton=tree_type.price_ton,
            transaction_hash=transaction_hash,
            status="completed",
            completed_at=timezone.now()
        )
        
        # Создаем дерево
        tree = Tree.objects.create(
            owner=user,
            tree_type=tree_type,
            level=1
        )
        
        # Создаем запись в истории транзакций
        Transaction.objects.create(
            user=user,
            type="tree_purchase",
            amount=tree_type.price_ton,
            currency="TON",
            description=f"Покупка дерева {tree_type.name}"
        )
        
        # Отправляем уведомление
        notify(user, f"🌳 Вы успешно приобрели дерево {tree_type.name}!")
        
        return tree