"""
Подписанный tg_id для ссылок мини-приложения.

Раньше сайт пускал по голому ?tg_id=<id>, и любой мог войти под чужим аккаунтом.
Теперь в ссылке передаётся токен вида "<id>:<время>:<подпись>". Подпись делается
ключом, который выводится из токена бота, поэтому её может выдать только бот или сайт.
Токен действует MAX_AGE секунд; после этого мини-приложение просто входит заново
через initData от Telegram.
"""
import hashlib

from django.conf import settings
from django.core import signing

SALT = "flora.webapp-login"
MAX_AGE = 7 * 24 * 3600


def _signer():
    bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "") or ""
    if not bot_token or bot_token == "YOUR_BOT_TOKEN":
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан — подписывать ссылки нечем")
    key = hashlib.sha256(("flora-webapp-link:" + bot_token).encode("utf-8")).hexdigest()
    return signing.TimestampSigner(key=key, salt=SALT)


def make_token(tg_id) -> str:
    return _signer().sign(str(int(tg_id)))


def read_token(value, max_age=MAX_AGE):
    """Возвращает telegram_id из подписанного токена или None, если токен поддельный/просрочен."""
    if not value or ":" not in str(value):
        return None
    try:
        return int(_signer().unsign(str(value), max_age=max_age))
    except (signing.BadSignature, ValueError, TypeError, RuntimeError):
        return None
