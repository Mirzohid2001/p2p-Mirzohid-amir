"""Общая логика регистрации, реферальной системы и уведомлений админам."""
import requests
from decimal import Decimal

from django.conf import settings

from users.models import User
from referrals.models import Referral, ReferralBonus


REFERRAL_BONUS = Decimal("100")
START_CF_BALANCE = Decimal("100")


def get_or_create_user(telegram_id, username="", first_name="", last_name="", photo_url=""):
    """Создаёт пользователя (с начальным деревом и балансом) или возвращает существующего."""
    user, created = User.objects.get_or_create(
        telegram_id=telegram_id,
        defaults={
            "username": username or "",
            "first_name": first_name or "",
            "last_name": last_name or "",
            "photo_url": photo_url or "",
        },
    )
    if created:
        user.cf_balance = START_CF_BALANCE
        user.save(update_fields=["cf_balance"])
        from trees.models import Tree
        Tree.objects.get_or_create(user=user, type="CF")
    else:
        changed = False
        for field, value in (
            ("username", username or ""),
            ("first_name", first_name or ""),
            ("last_name", last_name or ""),
            ("photo_url", photo_url or ""),
        ):
            # пустое значение не затирает уже известное (вход по ссылке приходит без имени)
            if value and getattr(user, field) != value:
                setattr(user, field, value)
                changed = True
        if changed:
            user.save(update_fields=["username", "first_name", "last_name", "photo_url"])
    return user, created


def apply_referral(invited_user, inviter_id):
    """Начисляет бонус 100 CF обоим участникам. Возвращает inviter или None."""
    if not inviter_id:
        return None
    try:
        inviter_id = int(inviter_id)
    except (ValueError, TypeError):
        return None

    if inviter_id == invited_user.telegram_id:
        return None
    # Один пользователь может быть приглашён только один раз
    if Referral.objects.filter(invited=invited_user).exists():
        return None

    inviter = User.objects.filter(telegram_id=inviter_id).first()
    if not inviter:
        return None

    referral = Referral.objects.create(
        inviter=inviter,
        invited=invited_user,
        bonus_cf=REFERRAL_BONUS,
    )
    ReferralBonus.objects.create(
        referral=referral,
        bonus_type="signup",
        amount=REFERRAL_BONUS,
        description=f"Бонус за приглашение @{invited_user.username or invited_user.first_name}",
    )
    ReferralBonus.objects.create(
        referral=referral,
        bonus_type="signup",
        amount=REFERRAL_BONUS,
        description=f"Бонус за регистрацию по реф. ссылке @{inviter.username or inviter.first_name}",
    )

    invited_user.referred_by = inviter
    invited_user.cf_balance += REFERRAL_BONUS
    invited_user.save(update_fields=["referred_by", "cf_balance"])

    inviter.cf_balance += REFERRAL_BONUS
    inviter.save(update_fields=["cf_balance"])

    return inviter


def get_bot_username():
    return getattr(settings, "TELEGRAM_BOT_USERNAME", None) or "FloraCoinBot"


def build_referral_link(telegram_id):
    return f"https://t.me/{get_bot_username()}?start={telegram_id}"


def get_admin_chat_ids():
    """Все активные админы: ADMIN_USER_ID из настроек + BotAdmin из БД."""
    ids = set()
    raw = getattr(settings, "ADMIN_USER_ID", "") or ""
    for part in str(raw).split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))

    from rps.models import BotAdmin
    for tg_id in BotAdmin.objects.filter(is_active=True).values_list("telegram_id", flat=True):
        ids.add(tg_id)
    return ids


def build_registration_message(user, inviter=None):
    name = user.username or user.first_name or str(user.telegram_id)
    if inviter:
        inviter_name = inviter.username or inviter.first_name or str(inviter.telegram_id)
        return (
            f"🆕 Новый пользователь!\n"
            f"👤 @{name} (ID {user.telegram_id})\n"
            f"🔗 Приглашён: @{inviter_name}"
        )
    return f"🆕 Новый пользователь!\n👤 @{name} (ID {user.telegram_id})"


def notify_admins_registration(user, inviter=None):
    """Синхронная отправка уведомления админам (для веб-части)."""
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
    if not token or token == "YOUR_BOT_TOKEN":
        return
    text = build_registration_message(user, inviter)
    for chat_id in get_admin_chat_ids():
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=10,
            )
        except Exception:
            continue
