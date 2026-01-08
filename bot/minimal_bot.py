import os
import sys

from _decimal import Decimal



# ──────────────────────────────────────────────────────────────────────────────
# 1) Вставляем корень проекта (D:\oxiri-p2p) в sys.path, чтобы Python видел cryptofarm.settings
# ──────────────────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ──────────────────────────────────────────────────────────────────────────────
# 2) Указываем Django‐настройки
# ──────────────────────────────────────────────────────────────────────────────
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cryptofarm.settings")

# ──────────────────────────────────────────────────────────────────────────────
# 3) Инициализируем Django (django.setup()), чтобы ORM работал
# ──────────────────────────────────────────────────────────────────────────────
import django
django.setup()

# ──────────────────────────────────────────────────────────────────────────────
# 4) Импортируем модель пользователя
# ──────────────────────────────────────────────────────────────────────────────
from users.models import User as TelegramUser

# ──────────────────────────────────────────────────────────────────────────────
# 5) Подключаем остальные библиотеки для бота
# ──────────────────────────────────────────────────────────────────────────────
import requests
import time
import logging
import json

# ─────────────── ДОБАВЬ ID своих админов! ────────────────
ADMIN_IDS = [1010942377,455168812]  # <-- замени на свой Telegram ID


# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Токен вашего бота (замените на реальный)
TOKEN = "8026375224:AAEi4Epjn6MviJMsUEjnsHnHfgGNZTucSYs"
API_URL = f"https://api.telegram.org/bot{TOKEN}"

WEBAPP_URL_BASE = "https://93d886f71258.ngrok-free.app/telegram_login/"

last_update_id = 0

# Для хранения состояний админов (ожидание суммы)
ADMIN_STATES = {}  # admin_id: {"action": "...", "target_id": ...}
BURN_STATES = {}

def get_updates():
    global last_update_id
    params = {
        "offset": last_update_id + 1,
        "timeout": 30,
        "allowed_updates": ["message", "callback_query"]
    }
    try:
        resp = requests.get(f"{API_URL}/getUpdates", params=params, timeout=35)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                results = data.get("result", [])
                if results:
                    last_update_id = results[-1]["update_id"]
                return results
            else:
                logger.error(f"Ошибка API getUpdates: {data}")
        else:
            logger.error(f"HTTP {resp.status_code} на getUpdates: {resp.text}")
    except Exception as e:
        logger.error(f"Исключение при getUpdates: {e}")
    return []

def send_message(chat_id, text, reply_markup=None):
    params = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        params["reply_markup"] = json.dumps(reply_markup)
    try:
        resp = requests.post(f"{API_URL}/sendMessage", json=params)
        result = resp.json()
        if not result.get("ok"):
            logger.error(f"Ошибка sendMessage: {result}")
        return result
    except Exception as e:
        logger.error(f"Исключение при sendMessage: {e}")
        return {"ok": False, "error": str(e)}

def edit_message(chat_id, message_id, text, reply_markup=None):
    params = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        params["reply_markup"] = json.dumps(reply_markup)
    try:
        resp = requests.post(f"{API_URL}/editMessageText", json=params)
        return resp.json()
    except Exception as e:
        logger.error(f"Ошибка editMessage: {e}")
        return None

def handle_message(message):
    from referrals.models import Referral, ReferralBonus  # Импортируй здесь, если не вверху

    chat_id = message["chat"]["id"]
    text = message.get("text", "")
    user_info = message.get("from", {})
    telegram_id = user_info.get("id")
    first_name = user_info.get("first_name", "Пользователь")

    logger.info(f"Получено сообщение: {text} от ID={telegram_id} ({first_name})")

    # --- 1. Проверяем, ждет ли админ сумму для изменения баланса ---
    if telegram_id in ADMIN_STATES and text.replace(',', '.').replace('-', '').replace('+', '').replace('.', '').isdigit():
        state = ADMIN_STATES.pop(telegram_id)
        act = state["action"]
        target_id = state["target_id"]
        amount_str = text.replace(',', '.')
        try:
            amount = Decimal(amount_str)
            target = TelegramUser.objects.get(telegram_id=target_id)
        except Exception:
            send_message(chat_id, "❌ Ошибка. Пользователь не найден или сумма некорректна.")
            return
        field = "cf_balance" if "fl" in act else "ton_balance"
        sign = 1 if "add" in act else -1
        old = getattr(target, field)
        new = old + sign * amount
        if "ton" in act and new < 0:
            send_message(chat_id, "TON баланс не может быть отрицательным!")
            return
        setattr(target, field, new)
        target.save(update_fields=[field])
        send_message(chat_id, f"Баланс обновлён!\n\n{field}: {old} → {new}")
        send_message(target.telegram_id, f"Ваш баланс {field.replace('_balance','').upper()} изменён админом: {old} → {new}")
        return

    # --- 2. Админ-команда /finduser ---
    if text.startswith("/finduser"):
        if telegram_id not in ADMIN_IDS:
            send_message(chat_id, "⛔️ Нет доступа.")
            return
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "Использование: /finduser <tg_id или @username>")
            return
        key = parts[1]
        user = None
        if key.startswith("@"):
            user = TelegramUser.objects.filter(username=key.lstrip("@")).first()
        else:
            try:
                user = TelegramUser.objects.get(telegram_id=int(key))
            except Exception:
                user = None
        if not user:
            send_message(chat_id, "Пользователь не найден.")
            return
        # Отправка инфы с инлайн-кнопками
        info = (
            f"👤 <b>{user.first_name} {user.last_name or ''}</b> (@{user.username or '-'})\n"
            f"Telegram ID: <code>{user.telegram_id}</code>\n"
            f"FL: <b>{user.cf_balance}</b>\n"
            f"TON: <b>{user.ton_balance}</b>"
        )
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "➕ FL", "callback_data": f"addfl_{user.telegram_id}"},
                    {"text": "➖ FL", "callback_data": f"subfl_{user.telegram_id}"},
                ],
                [
                    {"text": "➕ TON", "callback_data": f"addton_{user.telegram_id}"},
                    {"text": "➖ TON", "callback_data": f"subton_{user.telegram_id}"},
                ]
            ]
        }
        send_message(chat_id, info, keyboard)
        return

    if text == "/burn" and telegram_id in ADMIN_IDS:
        send_message(chat_id, "Введите сколько FL хотите сжечь (целое число, например 1000):")
        BURN_STATES[telegram_id] = True
        return

    # в функции handle_message
    if text == "/market_open" and telegram_id in ADMIN_IDS:
        from p2p.models import P2PSettings
        settings, _ = P2PSettings.objects.get_or_create(id=1)
        settings.is_market_open = True
        settings.save()
        send_message(chat_id, "✅ P2P-рынок ОТКРЫТ!")
        return

    if text == "/market_close" and telegram_id in ADMIN_IDS:
        from p2p.models import P2PSettings
        settings, _ = P2PSettings.objects.get_or_create(id=1)
        settings.is_market_open = False
        settings.save()
        send_message(chat_id, "⛔️ P2P-рынок ЗАКРЫТ!")
        return

    if telegram_id in BURN_STATES:
        # Вводим сумму для burn
        amount_str = text.replace(',', '.')
        try:
            amount = Decimal(amount_str)
            if amount <= 0:
                send_message(chat_id, "Ошибка: должно быть больше нуля.")
                return
        except Exception:
            send_message(chat_id, "Ошибка: введите число!")
            return
        # Записываем в базу
        admin_user = TelegramUser.objects.filter(telegram_id=telegram_id).first()
        from trees.models import BurnedToken
        BurnedToken.objects.create(amount=amount, admin=admin_user)
        send_message(chat_id, f"🔥 Сожжено {amount} FL.")
        BURN_STATES.pop(telegram_id, None)
        return

    # --- 3. Стандартная логика (регистрация, бонусы, игра и т.д.) ---
    inviter_id = None
    if text.startswith("/start"):
        args = text.split(" ")
        if len(args) > 1 and args[1].isdigit():
            inviter_id = int(args[1])

    is_new_user = not TelegramUser.objects.filter(telegram_id=telegram_id).exists()

    # Создаём или обновляем пользователя
    try:
        tg_user, created = TelegramUser.objects.get_or_create(
            telegram_id=telegram_id,
            defaults={
                "username": user_info.get("username") or "",
                "first_name": first_name,
                "last_name": user_info.get("last_name") or "",
                "photo_url": user_info.get("photo_url") or "",
            }
        )
        if not created:
            tg_user.username = user_info.get("username") or ""
            tg_user.first_name = first_name
            tg_user.last_name = user_info.get("last_name") or ""
            tg_user.photo_url = user_info.get("photo_url") or ""
            tg_user.save()
    except Exception as e:
        logger.error(f"Не удалось создать/обновить User: {e}")

    # Блок начисления бонуса за приглашение
    if is_new_user and inviter_id and inviter_id != telegram_id:
        try:
            inviter = TelegramUser.objects.filter(telegram_id=inviter_id).first()
            if inviter:
                already = Referral.objects.filter(inviter=inviter, invited=tg_user).exists()
                if not already:
                    referral = Referral.objects.create(inviter=inviter, invited=tg_user, bonus_cf=50)

                    inviter.cf_balance += 50
                    tg_user.cf_balance += 50
                    inviter.save()
                    tg_user.save()

                    ReferralBonus.objects.create(
                        referral=referral,
                        bonus_type='signup',
                        amount=50,
                        description=f'Бонус за приглашение @{tg_user.username or tg_user.first_name}'
                    )
                    ReferralBonus.objects.create(
                        referral=referral,
                        bonus_type='signup',
                        amount=50,
                        description=f'Бонус за регистрацию по реф. ссылке @{inviter.username or inviter.first_name}'
                    )

                    send_message(inviter.telegram_id, f"🎉 Вам начислено +50 токенов за приглашённого пользователя @{tg_user.username or tg_user.first_name}!")
                    send_message(chat_id, "🎁 Вам начислено +50 токенов за регистрацию по реферальной ссылке!")
        except Exception as e:
            logger.error(f"Ошибка при создании Referral и бонуса: {e}")



    if text.startswith("/start"):
        webapp_url = f"{WEBAPP_URL_BASE}?tg_id={telegram_id}"
        welcome_text = (
            f"Привет, {first_name}! 👋\n\n"
            "Ваша учётная запись успешно создана.\n"
            "Нажмите кнопку ниже, чтобы открыть игру."
        )
        webapp_button = {
            "inline_keyboard": [
                [
                    {
                        "text": "🌱 Играть",
                        "web_app": {"url": webapp_url}
                    }
                ]
            ]
        }
        send_message(chat_id, welcome_text, webapp_button)

    elif text == "/help":
        help_text = (
            "Доступные команды:\n"
            "/start — Зарегистрироваться и открыть игру\n"
            "/help  — Показать справку\n"
            "/ref   — Получить реферальную ссылку\n"
            "/finduser <tg_id или @username> — (админ) изменить баланс"
        )
        send_message(chat_id, help_text)

    elif text == "/play":
        webapp_url = f"{WEBAPP_URL_BASE}?tg_id={telegram_id}"
        play_text = "Нажмите кнопку ниже, чтобы открыть игру:"
        webapp_button = {
            "inline_keyboard": [
                [
                    {
                        "text": "🌱 Играть",
                        "web_app": {"url": webapp_url}
                    }
                ]
            ]
        }
        send_message(chat_id, play_text, webapp_button)

    elif text == "/ref":
        ref_url = f"{WEBAPP_URL_BASE}?tg_id={telegram_id}&ref={telegram_id}"
        ref_text = (
            f"Ваша реферальная ссылка:\n{ref_url}\n\n"
            "Поделитесь ею с друзьями, чтобы получить бонусы!"
        )
        ref_buttons = {
            "inline_keyboard": [
                [
                    {"text": "🔗 Пригласить друзей", "url": ref_url}
                ],
                [
                    {
                        "text": "🌱 Играть",
                        "web_app": {"url": ref_url}
                    }
                ]
            ]
        }
        send_message(chat_id, ref_text, ref_buttons)

    else:
        webapp_url = f"{WEBAPP_URL_BASE}?tg_id={telegram_id}"
        play_text = "Используйте /help или нажмите кнопку ниже, чтобы открыть игру:"
        webapp_button = {
            "inline_keyboard": [
                [
                    {
                        "text": "🌱 Играть",
                        "web_app": {"url": webapp_url}
                    }
                ]
            ]
        }
        send_message(chat_id, play_text, webapp_button)

# ================= CALLBACK ==========================
def handle_callback(callback):
    from users.models import User as TelegramUser
    query_id = callback["id"]
    data = callback["data"]
    message = callback["message"]
    chat_id = message["chat"]["id"]
    from_id = callback["from"]["id"]

    # Только для админа
    if from_id not in ADMIN_IDS:
        send_message(chat_id, "⛔️ Нет доступа.")
        return

    # Разбор callback_data
    if data.startswith(("addfl_", "subfl_", "addton_", "subton_")):
        act, user_id = data.split("_")
        # Сохраняем состояние (ожидаем сумму)
        ADMIN_STATES[from_id] = {"action": act, "target_id": int(user_id)}
        send_message(chat_id, f"Введите сумму для {'пополнения' if 'add' in act else 'вычета'} ({'FL' if 'fl' in act else 'TON'}):")
        return

if __name__ == "__main__":
    logger.info(f"Запускаем бота. Token={TOKEN[:5]}…, WebApp: {WEBAPP_URL_BASE}")

    # Сбрасываем webhook (если он был настроен)
    try:
        requests.get(f"{API_URL}/deleteWebhook?drop_pending_updates=true")
    except Exception as e:
        logger.error(f"Не удалось сбросить webhook: {e}")

    # Проверяем валидность токена
    try:
        me = requests.get(f"{API_URL}/getMe").json()
        if me.get("ok"):
            logger.info(f"Бот авторизован как @{me['result']['username']}")
        else:
            logger.error(f"Ошибка авторизации бота: {me}")
    except Exception as e:
        logger.error(f"Не удалось проверить токен: {e}")

    # Основной цикл getUpdates
    while True:
        try:
            updates = get_updates()
            for update in updates:
                if "message" in update:
                    handle_message(update["message"])
                if "callback_query" in update:
                    handle_callback(update["callback_query"])
            time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Бот остановлен вручную.")
            break
        except Exception as e:
            logger.error(f"Исключение в основном цикле: {e}")
            time.sleep(5)
