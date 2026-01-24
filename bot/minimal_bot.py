import asyncio
import os
import sys
import logging
from decimal import Decimal
from typing import Dict, Any, Optional, Tuple

import django
from asgiref.sync import sync_to_async

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo, BotCommand, MenuButtonWebApp,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.ext.filters import MessageFilter

# ──────────────────────────────────────────────────────────────────────────────
# Django setup
# ──────────────────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cryptofarm.settings")
django.setup()

from django.utils import timezone
from users.models import User as TelegramUser
from referrals.models import Referral, ReferralBonus
from trees.models import BurnedToken
from p2p.models import P2PSettings

from db_helpers import (
    check_is_admin,
    get_active_tournament,
    create_tournament,
    get_completed_tournament,
    complete_tournament,
    get_tournament_top_10,
    reward_participant,
    mark_tournament_rewarded,
    get_user_by_username,
    get_user_by_telegram_id,
    check_bot_admin_exists,
    create_bot_admin,
    get_bot_admin,
    deactivate_bot_admin,
    get_all_bot_admins,
)
from asgiref.sync import sync_to_async
from django.db.models import Q, F
from django.utils import timezone

from trees.models import Tree
# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")
WEBAPP_URL_BASE = os.getenv("WEBAPP_URL_BASE", "https://flora.diy/telegram_login/")

ADMIN_IDS = [1010942377, 455168812]
class AdminOnly(MessageFilter):
    def filter(self, message):
        return bool(message and message.from_user and message.from_user.id in ADMIN_IDS)

ADMIN_ONLY = AdminOnly()


ADMIN_STATES: Dict[int, Dict[str, Any]] = {}
BURN_STATES: Dict[int, bool] = {}
BROADCAST_STATES: Dict[int, bool] = {}

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _webapp_url(tg_id: int, ref: Optional[int] = None) -> str:
    url = f"{WEBAPP_URL_BASE}?tg_id={tg_id}"
    if ref:
        url += f"&ref={ref}"
    return url

def _play_keyboard(tg_id: int, ref: Optional[int] = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌱 Играть", web_app=WebAppInfo(url=_webapp_url(tg_id, ref)))]
    ])

def _is_number_like(s: str) -> bool:
    if not s:
        return False
    t = s.replace(",", ".").replace("+", "").replace("-", "")
    return t.replace(".", "", 1).isdigit()

async def _is_admin(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    try:
        return await check_is_admin(user_id, str(user_id))
    except Exception:
        return False

# ──────────────────────────────────────────────────────────────────────────────
# DB wrappers (важно для async PTB)
# ────────────
#
# ──────────────────────────────────────────────────────────────────
@sync_to_async
def db_user_exists(telegram_id: int) -> bool:
    return TelegramUser.objects.filter(telegram_id=telegram_id).exists()


@sync_to_async
def db_get_trees_to_remind(limit: int = 500):
    now = timezone.now()
    due_time = now - timezone.timedelta(hours=Tree.WATER_DURATION)

    qs = (
        Tree.objects.select_related("user")
        # напоминать только тем, кого вообще можно уведомить
        .filter(user__telegram_id__isnull=False)

        # напоминать только если полив уже был хотя бы раз
        .filter(last_watered__isnull=False)

        # автополив НЕ активен
        .filter(Q(auto_water_until__isnull=True) | Q(auto_water_until__lte=now))

        # вода закончилась
        .filter(last_watered__lte=due_time)

        # напоминание ещё не отправляли после последнего полива
        .filter(Q(water_reminder_sent_at__isnull=True) | Q(water_reminder_sent_at__lt=F("last_watered")))

        .order_by("id")
    )
    return list(qs[:limit])

@sync_to_async
def db_mark_reminded(tree_id, ts):
    Tree.objects.filter(id=tree_id).update(water_reminder_sent_at=ts)
async def notify_water_due_job(context: ContextTypes.DEFAULT_TYPE):
    now = timezone.now()
    trees = await db_get_trees_to_remind()

    for tree in trees:
        tg_id = getattr(tree.user, "telegram_id", None)
        if not tg_id:
            continue

        tree_name = "🌱 FLORA" if tree.type == "CF" else "💎 TON"

        try:
            await context.bot.send_message(
                chat_id=tg_id,
                text=f"💧 Пора поливать! {tree_name}-дерево высохло — полейте, чтобы снова шёл доход.",
                reply_markup=_play_keyboard(tg_id)
            )
        except Exception:
            continue

        # помечаем в БД что напоминание отправлено
        await db_mark_reminded(tree.id, now)

@sync_to_async
def db_get_or_create_user(telegram_id: int, username: str, first_name: str, last_name: str) -> Tuple[TelegramUser, bool]:
    tg_user, created = TelegramUser.objects.get_or_create(
        telegram_id=telegram_id,
        defaults={
            "username": username or "",
            "first_name": first_name or "",
            "last_name": last_name or "",
            "photo_url": "",
        }
    )
    if not created:
        changed = False
        if tg_user.username != (username or ""):
            tg_user.username = username or ""
            changed = True
        if tg_user.first_name != (first_name or ""):
            tg_user.first_name = first_name or ""
            changed = True
        if tg_user.last_name != (last_name or ""):
            tg_user.last_name = last_name or ""
            changed = True
        if changed:
            tg_user.save()
    return tg_user, created

@sync_to_async
def db_apply_referral_bonus(inviter_id: int, invited_user_id: int) -> Dict[str, Any]:
    """
    Возвращает:
      {"ok": bool, "inviter_tg_id": int|None, "invited_name": str}
    """
    invited = TelegramUser.objects.filter(telegram_id=invited_user_id).first()
    if not invited:
        return {"ok": False, "inviter_tg_id": None, "invited_name": ""}

    if inviter_id == invited_user_id:
        return {"ok": False, "inviter_tg_id": None, "invited_name": invited.username or invited.first_name}

    inviter = TelegramUser.objects.filter(telegram_id=inviter_id).first()
    if not inviter:
        return {"ok": False, "inviter_tg_id": None, "invited_name": invited.username or invited.first_name}

    already = Referral.objects.filter(inviter=inviter, invited=invited).exists()
    if already:
        return {"ok": False, "inviter_tg_id": inviter.telegram_id, "invited_name": invited.username or invited.first_name}

    referral = Referral.objects.create(inviter=inviter, invited=invited, bonus_cf=50)

    inviter.cf_balance += 50
    invited.cf_balance += 50
    inviter.save()
    invited.save()

    ReferralBonus.objects.create(
        referral=referral,
        bonus_type='signup',
        amount=50,
        description=f'Бонус за приглашение @{invited.username or invited.first_name}'
    )
    ReferralBonus.objects.create(
        referral=referral,
        bonus_type='signup',
        amount=50,
        description=f'Бонус за регистрацию по реф. ссылке @{inviter.username or inviter.first_name}'
    )

    return {"ok": True, "inviter_tg_id": inviter.telegram_id, "invited_name": invited.username or invited.first_name}

@sync_to_async
def db_find_user_by_username(username: str):
    return TelegramUser.objects.filter(username=username).first()

@sync_to_async
def db_find_user_by_tg_id(tg_id: int):
    return TelegramUser.objects.filter(telegram_id=tg_id).first()

@sync_to_async
def db_get_user_by_tg_id_strict(tg_id: int):
    return TelegramUser.objects.get(telegram_id=tg_id)

@sync_to_async
def db_update_balance(target_id: int, field: str, amount: Decimal, sign: int) -> Dict[str, Any]:
    target = TelegramUser.objects.filter(telegram_id=target_id).first()
    if not target:
        return {"ok": False, "error": "user_not_found"}

    old = getattr(target, field)
    new = old + (Decimal(sign) * amount)

    if field == "ton_balance" and new < 0:
        return {"ok": False, "error": "ton_negative", "old": old, "new": new}

    setattr(target, field, new)
    target.save(update_fields=[field])
    return {"ok": True, "old": old, "new": new, "target_tg_id": target.telegram_id}

@sync_to_async
def db_burn(admin_tg_id: int, amount: Decimal) -> bool:
    admin_user = TelegramUser.objects.filter(telegram_id=admin_tg_id).first()
    BurnedToken.objects.create(amount=amount, admin=admin_user)
    return True

@sync_to_async
def db_set_market_open(is_open: bool) -> None:
    settings, _ = P2PSettings.objects.get_or_create(id=1)
    settings.is_market_open = is_open
    settings.save()
@sync_to_async
def db_get_all_user_ids():
    return list(
        TelegramUser.objects
        .exclude(telegram_id__isnull=True)
        .values_list("telegram_id", flat=True)
    )

# ──────────────────────────────────────────────────────────────────────────────
# /start
# ───────────────────────────────────────────────────────────────────────────
#
# ───
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    telegram_id = user.id
    first_name = user.first_name or "Пользователь"
    username = user.username or ""
    last_name = user.last_name or ""

    inviter_id = None
    if context.args and context.args[0].isdigit():
        inviter_id = int(context.args[0])

    is_new_user = not await db_user_exists(telegram_id)

    tg_user, created = await db_get_or_create_user(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
    )

    # referral bonus
    if is_new_user and inviter_id:
        res = await db_apply_referral_bonus(inviter_id, telegram_id)
        if res.get("ok"):
            try:
                await context.bot.send_message(
                    res["inviter_tg_id"],
                    f"🎉 Вам начислено +50 FL за приглашённого пользователя @{res['invited_name']}!",
                    reply_markup=_play_keyboard(res["inviter_tg_id"])
                )
            except Exception:
                pass
            await update.message.reply_text("🎁 Вам начислено +50 FL за регистрацию по реферальной ссылке!")

    welcome_text = (
        f"Привет, {first_name}! 👋\n\n"
        "Ваша учётная запись успешно создана.\n"
        "Нажмите кнопку ниже, чтобы открыть игру."
    )
    await update.message.reply_text(welcome_text, reply_markup=_play_keyboard(telegram_id, inviter_id))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "Команды:\n"
        "/start — открыть игру\n"
        "/play — открыть игру\n"
        "/ref — реферальная ссылка\n"
        "/help — справка\n\n"
        "Админ:\n"
        "/finduser <tg_id или @username>\n"
        "/burn\n"
        "/market_open\n"
        "/market_close\n"
        "/myid\n"
        "/addadmin /removeadmin /listadmins\n"
        "/tyrnir /priz\n"
    )
    await update.message.reply_text(txt)


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await _is_admin(user_id):
        await update.message.reply_text("⛔️ Нет доступа.")
        return

    BROADCAST_STATES[user_id] = True
    await update.message.reply_text(
        "📣 Отправь СЛЕДУЮЩИМ сообщением:\n"
        "• текст — для текстовой рассылки\n"
        "• ИЛИ фото с подписью — для рассылки с изображением\n\n"
        "⚠️ Будет отправлено всем пользователям."
    )

async def play_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    await update.message.reply_text("Нажмите кнопку ниже, чтобы открыть игру:", reply_markup=_play_keyboard(telegram_id))

async def ref_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    ref_url = f"{WEBAPP_URL_BASE}?tg_id={telegram_id}&ref={telegram_id}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Пригласить друзей", url=ref_url)],
        [InlineKeyboardButton("🌱 Играть", web_app=WebAppInfo(url=ref_url))]
    ])
    await update.message.reply_text(
        f"Ваша реферальная ссылка:\n{ref_url}\n\nПоделитесь ею с друзьями, чтобы получить бонусы!",
        reply_markup=kb
    )

# ──────────────────────────────────────────────────────────────────────────────
# Admin: /finduser
# ──────────────────────────────────────────────────────────────────────────────
async def finduser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await _is_admin(user_id):
        await update.message.reply_text("⛔️ Нет доступа.")
        return

    if not context.args:
        await update.message.reply_text("Использование: /finduser <tg_id или @username>")
        return

    key = context.args[0]
    target = None

    if key.startswith("@"):
        target = await db_find_user_by_username(key.lstrip("@"))
    else:
        try:
            target = await db_find_user_by_tg_id(int(key))
        except Exception:
            target = None

    if not target:
        await update.message.reply_text("Пользователь не найден.")
        return

    info = (
        f"👤 <b>{target.first_name} {target.last_name or ''}</b> (@{target.username or '-'})\n"
        f"Telegram ID: <code>{target.telegram_id}</code>\n"
        f"FL: <b>{target.cf_balance}</b>\n"
        f"TON: <b>{target.ton_balance}</b>"
    )

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ FL", callback_data=f"addfl_{target.telegram_id}"),
            InlineKeyboardButton("➖ FL", callback_data=f"subfl_{target.telegram_id}"),
        ],
        [
            InlineKeyboardButton("➕ TON", callback_data=f"addton_{target.telegram_id}"),
            InlineKeyboardButton("➖ TON", callback_data=f"subton_{target.telegram_id}"),
        ]
    ])

    await update.message.reply_text(info, reply_markup=kb, parse_mode="HTML")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    from_id = query.from_user.id

    if not await _is_admin(from_id):
        await query.message.reply_text("⛔️ Нет доступа.")
        return

    data = query.data or ""
    if data.startswith(("addfl_", "subfl_", "addton_", "subton_")):
        act, user_id_str = data.split("_", 1)
        try:
            target_id = int(user_id_str)
        except Exception:
            await query.message.reply_text("Ошибка callback.")
            return

        ADMIN_STATES[from_id] = {"action": act, "target_id": target_id}
        what = "FL" if "fl" in act else "TON"
        verb = "пополнения" if "add" in act else "вычета"
        await query.message.reply_text(f"Введите сумму для {verb} ({what}):")
        return

# ──────────────────────────────────────────────────────────────────────────────
# Text router
# ──────────────────────────────────────────────────────────────────────────────
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    telegram_id = update.effective_user.id

    # 1) Админ ждёт сумму для add/sub
    # ───── BROADCAST (text / photo) ─────
    if telegram_id in BROADCAST_STATES:
        BROADCAST_STATES.pop(telegram_id, None)

        user_ids = await db_get_all_user_ids()
        sent = 0
        failed = 0



        await update.message.reply_text(
            f"🚀 Начинаю рассылку...\nПолучателей: {len(user_ids)}"
        )

        # ─── ЕСЛИ ФОТО ───
        if update.message.photo:
            photo = update.message.photo[-1].file_id
            caption = update.message.caption or ""

            for uid in user_ids:
                try:
                    await context.bot.send_photo(
                        chat_id=uid,
                        photo=photo,
                        caption=caption,
                        reply_markup=_play_keyboard(uid)

                    )
                    sent += 1
                except Exception:
                    failed += 1
                await asyncio.sleep(0.05)

        # ─── ЕСЛИ ТЕКСТ ───
        else:
            text_to_send = update.message.text or ""
            for uid in user_ids:
                try:
                    await context.bot.send_message(
                        chat_id=uid,
                        text=text_to_send,
                        reply_markup=_play_keyboard(uid)
                    )
                    sent += 1
                except Exception:
                    failed += 1
                await asyncio.sleep(0.05)

        await update.message.reply_text(
            f"✅ Рассылка завершена!\n\n"
            f"📤 Отправлено: {sent}\n"
            f"❌ Ошибок: {failed}"
        )
        return

    if telegram_id in ADMIN_STATES and _is_number_like(text):
        state = ADMIN_STATES.pop(telegram_id)
        act = state["action"]
        target_id = state["target_id"]

        amount = Decimal(text.replace(",", "."))
        field = "cf_balance" if "fl" in act else "ton_balance"
        sign = 1 if "add" in act else -1

        res = await db_update_balance(target_id, field, amount, sign)
        if not res.get("ok"):
            if res.get("error") == "ton_negative":
                await update.message.reply_text("TON баланс не может быть отрицательным!")
            else:
                await update.message.reply_text("❌ Ошибка. Пользователь не найден.")
            return

        old = res["old"]
        new = res["new"]

        await update.message.reply_text(f"✅ Баланс обновлён!\n\n{field}: {old} → {new}")
        try:
            await context.bot.send_message(
                res["target_tg_id"],
                f"Ваш баланс {field.replace('_balance','').upper()} изменён админом: {old} → {new}"
            )
        except Exception:
            pass
        return

    # 2) burn state
    if telegram_id in BURN_STATES:
        if not _is_number_like(text):
            await update.message.reply_text("Ошибка: введите число!")
            return
        amount = Decimal(text.replace(",", "."))
        if amount <= 0:
            await update.message.reply_text("Ошибка: должно быть больше нуля.")
            return

        await db_burn(telegram_id, amount)
        BURN_STATES.pop(telegram_id, None)
        await update.message.reply_text(f"🔥 Сожжено {amount} FL.")
        return

    # 3) default reply
    await update.message.reply_text(
        "Используйте /help или нажмите кнопку, чтобы открыть игру:",
        reply_markup=_play_keyboard(telegram_id)
    )

# ──────────────────────────────────────────────────────────────────────────────
# /burn, /market_open, /market_close
# ──────────────────────────────────────────────────────────────────────────────
async def burn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await _is_admin(user_id):
        await update.message.reply_text("⛔️ Нет доступа.")
        return
    BURN_STATES[user_id] = True
    await update.message.reply_text("Введите сколько FL хотите сжечь (например 1000):")

async def market_open_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await _is_admin(user_id):
        await update.message.reply_text("⛔️ Нет доступа.")
        return
    await db_set_market_open(True)
    await update.message.reply_text("✅ P2P-рынок ОТКРЫТ!")

async def market_close_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await _is_admin(user_id):
        await update.message.reply_text("⛔️ Нет доступа.")
        return
    await db_set_market_open(False)
    await update.message.reply_text("⛔️ P2P-рынок ЗАКРЫТ!")

# ──────────────────────────────────────────────────────────────────────────────
# Commands from main.py (оставил как есть, они уже async и внутри db_helpers могут быть async-safe)
# ──────────────────────────────────────────────────────────────────────────────
async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(f"🆔 Ваш Telegram ID: {user.id}")

async def addadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await _is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /addadmin <telegram_id> или /addadmin @username")
        return

    arg = context.args[0]
    if arg.startswith("@"):
        target_user = await get_user_by_username(arg[1:])
        if not target_user:
            await update.message.reply_text(f"❌ Пользователь {arg} не найден.")
            return
        target_id = target_user.telegram_id
    else:
        target_id = int(arg)
        target_user = await get_user_by_telegram_id(target_id)
        if not target_user:
            await update.message.reply_text(f"❌ Пользователь с ID {target_id} не найден.")
            return

    if await check_bot_admin_exists(target_id):
        await update.message.reply_text("⚠️ Этот пользователь уже администратор.")
        return

    current_admin_user = await get_user_by_telegram_id(user_id)
    await create_bot_admin(target_user, target_id, current_admin_user)
    await update.message.reply_text(f"✅ Админ добавлен: {target_user} (ID {target_id})")

async def removeadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await _is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /removeadmin <telegram_id> или /removeadmin @username")
        return

    arg = context.args[0]
    if arg.startswith("@"):
        target_user = await get_user_by_username(arg[1:])
        if not target_user:
            await update.message.reply_text(f"❌ Пользователь {arg} не найден.")
            return
        target_id = target_user.telegram_id
    else:
        target_id = int(arg)

    if target_id == user_id:
        await update.message.reply_text("⚠️ Нельзя удалить самого себя.")
        return

    admin = await get_bot_admin(target_id)
    if not admin:
        await update.message.reply_text("❌ Этот пользователь не администратор.")
        return

    await deactivate_bot_admin(admin)
    await update.message.reply_text(f"✅ Админ удалён (ID {target_id})")

async def listadmins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await _is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав.")
        return

    admins = await get_all_bot_admins()
    if not admins:
        await update.message.reply_text("📋 Список админов пуст.")
        return

    msg = "👥 Администраторы:\n\n"
    for i, a in enumerate(admins, 1):
        msg += f"{i}. {a.user} — {a.telegram_id}\n"
    await update.message.reply_text(msg)

async def tyrnir_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await _is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав.")
        return

    active = await get_active_tournament()
    if active:
        await update.message.reply_text(f"⚠️ Турнир уже активен! ID: {active.id}")
        return

    tournament, end_date = await create_tournament()
    await update.message.reply_text(
        f"✅ Турнир запущен!\nID: {tournament.id}\n"
        f"Начало: {tournament.start_date.strftime('%d.%m.%Y %H:%M')}\n"
        f"Окончание: {end_date.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"🏆 Start of a new tournament."
    )
def mask_username(username: str, visible: int = 3) -> str:
    if not username:
        return "unknown"

    prefix = "@"
    name = username[1:] if username.startswith("@") else username
    if len(name) <= visible:
        masked = "*" * len(name)
    else:
        masked = name[:-visible] + "*" * visible

    return prefix + masked


async def priz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await _is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав.")
        return

    completed = await get_completed_tournament()
    if not completed:
        active = await get_active_tournament()
        if active and active.end_date and timezone.now() > active.end_date:
            completed = await complete_tournament(active)
        else:
            await update.message.reply_text("❌ Нет завершенного турнира.")
            return

    top_10 = await get_tournament_top_10(completed)
    if not top_10:
        await update.message.reply_text("❌ Нет участников.")
        return

    rewards = {1:1000,2:900,3:800,4:700,5:600,6:500,7:400,8:300,9:200,10:100}

    msg = "🏆 Награды выданы:\n\n"
    count = 0
    for idx, participant in enumerate(top_10, 1):
        if idx in rewards:
            amt = rewards[idx]
            await reward_participant(participant, amt)
            username = getattr(participant.user, "username", None)
            masked_name = mask_username(username or str(participant.user))

            msg += f"{idx}. {masked_name} — {amt} FL\n"

            count += 1

    await mark_tournament_rewarded(completed)
    msg += f"\n✅ Выдано наград: {count}"
    await update.message.reply_text(msg)

async def post_init(application: Application):
    # команды в списке / (не обязательно, но удобно)
    await application.bot.set_my_commands([
        BotCommand("start", "Открыть игру")
    ])

    # кнопка меню слева (Menu Button) -> открывает WebApp
    await application.bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="Играть",
            web_app=WebAppInfo(url=WEBAPP_URL_BASE)
        )
    )


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────
def main():
    if BOT_TOKEN == "PUT_YOUR_TOKEN_HERE":
        print("❌ Укажи BOT_TOKEN в переменных окружения или в коде.")
        return

    from telegram.request import HTTPXRequest

    request = HTTPXRequest(
        connect_timeout=20.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )

    app = Application.builder().token(BOT_TOKEN).request(request).post_init(post_init).build()
    app.job_queue.run_repeating(
        notify_water_due_job,
        interval=60,  # проверка каждую минуту
        first=10,
        name="notify_water_due"
    )


    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command,filters=ADMIN_ONLY))
    app.add_handler(CommandHandler("play", play_command))
    app.add_handler(CommandHandler("ref", ref_command))

    app.add_handler(CommandHandler("finduser", finduser_command,filters=ADMIN_ONLY))
    app.add_handler(CommandHandler("burn", burn_command,filters=ADMIN_ONLY))
    app.add_handler(CommandHandler("market_open", market_open_command,filters=ADMIN_ONLY))
    app.add_handler(CommandHandler("market_close", market_close_command,filters=ADMIN_ONLY))

    app.add_handler(CommandHandler("broadcast", broadcast_command,filters=ADMIN_ONLY))
    app.add_handler(CommandHandler("myid", myid_command))
    app.add_handler(CommandHandler("addadmin", addadmin_command,filters=ADMIN_ONLY))
    app.add_handler(CommandHandler("removeadmin", removeadmin_command,filters=ADMIN_ONLY))
    app.add_handler(CommandHandler("listadmins", listadmins_command,filters=ADMIN_ONLY))
    app.add_handler(CommandHandler("tyrnir", tyrnir_command,filters=ADMIN_ONLY))
    app.add_handler(CommandHandler("priz", priz_command,filters=ADMIN_ONLY))

    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, text_router))

    logger.info("✅ Bot started (polling)")
    app.run_polling(allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    main()
