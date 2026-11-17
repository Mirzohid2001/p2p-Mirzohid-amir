"""
Отложенный бонус пригласившему.

Приглашённый получает свои +100 FL сразу при регистрации, а пригласивший —
только когда приглашённый сделал обе вещи: полил дерево и сыграл хотя бы одну
игру в КНБ. Так фермы пустых аккаунтов больше ничего не приносят.

maybe_reward_inviter(user) вызывается после полива и после завершения игры КНБ.
"""
import logging
import threading
from decimal import Decimal
from urllib.parse import quote

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import F, Q

INVITER_BONUS = Decimal("100")
SITE_URL = getattr(settings, "SITE_URL", "https://floracoin.cc")

TEXT = {
    "ru": ("🎉 Ваш друг @{name} полил дерево и сыграл в КНБ — вам начислено +100 FL!", "🌱 Играть"),
    "en": ("🎉 Your friend @{name} watered a tree and played RPS — you got +100 FL!", "🌱 Play"),
}

log = logging.getLogger(__name__)


def conditions_met(user):
    from rps.models import Game
    from trees.models import Tree

    watered = Tree.objects.filter(user=user, last_watered__isnull=False).exists()
    if not watered:
        return False
    return Game.objects.filter(Q(player1=user) | Q(player2=user), status="finished").exists()


def maybe_reward_inviter(user):
    """Начисляет бонус пригласившему, если условия выполнены. Ошибки не ломают полив/игру."""
    from referrals.models import Referral, ReferralBonus
    from users.models import User

    try:
        ref = Referral.objects.filter(invited_id=user.pk, inviter_rewarded=False).select_related("inviter").first()
        if not ref or not conditions_met(user):
            return False
        with transaction.atomic():
            # атомарно: параллельный полив и игра не начислят бонус дважды
            if not Referral.objects.filter(pk=ref.pk, inviter_rewarded=False).update(
                inviter_rewarded=True, bonus_cf=INVITER_BONUS
            ):
                return False
            User.objects.filter(pk=ref.inviter_id).update(cf_balance=F("cf_balance") + INVITER_BONUS)
            name = user.username or user.first_name or str(user.telegram_id)
            ReferralBonus.objects.create(
                referral=ref,
                bonus_type="signup",
                amount=INVITER_BONUS,
                description=f"Бонус за приглашение @{name} (полил дерево и сыграл в КНБ)",
            )
            inviter = ref.inviter
            msg = (inviter.telegram_id, (inviter.language or "ru").lower(), name)
            transaction.on_commit(lambda: threading.Thread(target=_send, args=(msg,), daemon=True).start())
        return True
    except Exception:
        log.exception("Не удалось начислить реферальный бонус за пользователя %s", getattr(user, "pk", None))
        return False


def _send(msg):
    telegram_id, lang, name = msg
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if not token or token == "YOUR_BOT_TOKEN" or token.startswith("0:"):
        return
    from users.auth_token import make_token

    text, button = TEXT.get(lang, TEXT["ru"])
    url = f"{SITE_URL}/?tg_id={quote(make_token(telegram_id))}"
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={
            "chat_id": telegram_id,
            "text": text.format(name=name),
            "reply_markup": {"inline_keyboard": [[{"text": button, "web_app": {"url": url}}]]},
        }, timeout=10)
    except Exception:
        log.warning("Не удалось отправить уведомление о реферальном бонусе %s", telegram_id)
