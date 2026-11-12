import asyncio
import logging
import os
import sys
import django
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from datetime import timedelta
from asgiref.sync import sync_to_async

# Импорт конфигурации
from config import BOT_TOKEN, WEBAPP_URL, ADMIN_USER_ID, print_config_info


def play_webapp_url(user_id, extra=None):
    """URL Mini App с tg_id — на iOS cookie часто не сохраняются."""
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    parts = urlsplit(WEBAPP_URL)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    from users.auth_token import make_token  # подписанный tg_id, голый больше не принимается
    q["tg_id"] = make_token(user_id)
    if extra:
        q.update({k: str(v) for k, v in extra.items() if v is not None})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), parts.fragment))

# Настройка Django для использования моделей
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cryptofarm.settings')
django.setup()

from users.models import User
from users.services import get_or_create_user, apply_referral, get_admin_chat_ids, build_registration_message, build_referral_link
from rps.models import BotAdmin, Tournament, TournamentParticipant
from db_helpers import (
    check_is_admin, get_active_tournament, create_tournament,
    get_completed_tournament, complete_tournament, get_tournament_top_10,
    reward_participant, mark_tournament_rewarded,
    get_user_by_username, get_user_by_telegram_id,
    check_bot_admin_exists, create_bot_admin,
    get_bot_admin, deactivate_bot_admin, get_all_bot_admins
)

# Импорт Django моделей после настройки
from django.utils import timezone
from users.models import User

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def notify_admins_registration(context: ContextTypes.DEFAULT_TYPE, user, inviter=None):
    """Асинхронная отправка уведомления админам (для бота)."""
    try:
        ids = await sync_to_async(get_admin_chat_ids)()
        text = build_registration_message(user, inviter)
        for chat_id in ids:
            try:
                await context.bot.send_message(chat_id=chat_id, text=text)
            except Exception:
                continue
    except Exception:
        pass


# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    tg_user = update.effective_user
    tg_id = tg_user.id

    user, created = await sync_to_async(get_or_create_user)(
        tg_id,
        username=tg_user.username or "",
        first_name=tg_user.first_name or "",
        last_name=tg_user.last_name or "",
        photo_url="",
    )

    inviter = None
    if created and context.args and context.args[0].isdigit():
        inviter = await sync_to_async(apply_referral)(user, int(context.args[0]))

    if created:
        await notify_admins_registration(context, user, inviter)

    # Создаем клавиатуру с кнопкой для открытия веб-приложения
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(text="🌱 Играть", web_app=WebAppInfo(url=play_webapp_url(tg_id)))]
    ])

    # Текст приветствия
    welcome_text = (
        f"Привет, {tg_user.first_name}! 👋\n\n"
        "Добро пожаловать в Crypto Farm!\n\n"
        "Нажми на кнопку ниже, чтобы открыть игру:"
    )

    await update.message.reply_text(welcome_text, reply_markup=keyboard)

# Обработчик команды /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = (
        "Доступные команды:\n"
        "/start - Начать взаимодействие с ботом\n"
        "/help - Показать справку\n"
        "/play - Открыть игру\n"
        "/ref - Получить реферальную ссылку"
    )
    await update.message.reply_text(help_text)

# Обработчик команды /play
async def play_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /play"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(text="🌱 Играть", web_app=WebAppInfo(url=play_webapp_url(update.effective_user.id)))]
    ])
    
    await update.message.reply_text("Нажми на кнопку ниже, чтобы открыть игру:", reply_markup=keyboard)

# Обработчик команды /ref
async def ref_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /ref"""
    user_id = update.effective_user.id
    ref_url = build_referral_link(user_id)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(text="🔗 Пригласить друзей", url=ref_url)],
        [InlineKeyboardButton(text="🌱 Играть", web_app=WebAppInfo(url=play_webapp_url(user_id)))]
    ])
    
    ref_text = (
        f"Ваша реферальная ссылка:\n{ref_url}\n\n"
        f"Поделитесь ею с друзьями, чтобы получить бонусы!"
    )
    
    await update.message.reply_text(ref_text, reply_markup=keyboard)

# Обработчик команды /tyrnir (запуск турнира, только для админов)
async def is_admin(user_id):
    """Проверяет, является ли пользователь администратором"""
    return await check_is_admin(user_id, ADMIN_USER_ID)

async def tyrnir_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /tyrnir - запуск нового турнира"""
    user_id = update.effective_user.id
    
    # Проверка прав администратора
    if not await is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    
    # Проверяем, есть ли активный турнир
    active_tournament = await get_active_tournament()
    if active_tournament:
        await update.message.reply_text(
            f"⚠️ Турнир уже активен!\n"
            f"ID: {active_tournament.id}\n"
            f"Начало: {active_tournament.start_date.strftime('%d.%m.%Y %H:%M')}"
        )
        return
    
    # Создаем новый турнир
    tournament, end_date = await create_tournament()
    
    # Отправляем уведомление о начале турнира (как в ТЗ)
    notification_text = "🏆 Start of a new tournament."
    
    # Отправляем уведомление администратору
    await update.message.reply_text(
        f"✅ Турнир запущен!\n\n"
        f"ID: {tournament.id}\n"
        f"Начало: {tournament.start_date.strftime('%d.%m.%Y %H:%M')}\n"
        f"Окончание: {end_date.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"Турнир продлится 6 дней, затем будет день для выдачи наград.\n\n"
        f"{notification_text}"
    )
    
    # Планируем автоматическую остановку через 6 дней
    # В продакшене это должно быть через Celery или cron
    logging.info(f"Tournament {tournament.id} started. Will end at {end_date}")
    
    # TODO: Отправить уведомление всем пользователям через бота
    # Это можно сделать через Celery task или отдельный скрипт

# Обработчик команды /priz (выдача наград, только для админов)
async def priz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /priz - выдача наград за турнир"""
    user_id = update.effective_user.id
    
    # Проверка прав администратора
    if not await is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    
    # Ищем завершенный турнир без выданных наград
    completed_tournament = await get_completed_tournament()
    
    if not completed_tournament:
        # Проверяем активный турнир, который должен быть завершен
        active_tournament = await get_active_tournament()
        if active_tournament and active_tournament.end_date:
            from django.utils import timezone
            if timezone.now() > active_tournament.end_date:
                # Автоматически завершаем турнир
                completed_tournament = await complete_tournament(active_tournament)
            else:
                await update.message.reply_text("❌ Нет завершенного турнира для выдачи наград.")
                return
        else:
            await update.message.reply_text("❌ Нет завершенного турнира для выдачи наград.")
            return
    
    # Получаем топ-10
    top_10 = await get_tournament_top_10(completed_tournament)
    
    if not top_10:
        await update.message.reply_text("❌ Нет участников в турнире.")
        return
    
    # Награды для топ-10
    rewards = {
        1: 1000,
        2: 900,
        3: 800,
        4: 700,
        5: 600,
        6: 500,
        7: 400,
        8: 300,
        9: 200,
        10: 100,
    }
    
    rewarded_count = 0
    reward_message = "🏆 Награды выданы:\n\n"
    
    for idx, participant in enumerate(top_10, 1):
        if idx in rewards:
            reward_amount = rewards[idx]
            await reward_participant(participant, reward_amount)
            reward_message += f"{idx}. {participant.user} - {reward_amount} FL\n"
            rewarded_count += 1
    
    # Обновляем статус турнира
    await mark_tournament_rewarded(completed_tournament)
    
    reward_message += f"\n✅ Выдано наград: {rewarded_count}"
    
    await update.message.reply_text(reward_message)

# Обработчик для всех остальных сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик всех остальных сообщений"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(text="🌱 Играть", web_app=WebAppInfo(url=play_webapp_url(update.effective_user.id)))]
    ])
    
    await update.message.reply_text(
        "Используйте /help для списка команд или нажмите кнопку, чтобы открыть игру:",
        reply_markup=keyboard
    )

# Команда для получения ID пользователя (для настройки ADMIN_USER_ID)
async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает ID пользователя для настройки администратора"""
    user = update.effective_user
    await update.message.reply_text(
        f"🆔 Ваш Telegram ID: `{user.id}`\n\n"
        f"Чтобы установить себя как администратора, добавьте эту строку в файл `.env` в папке `bot/`:\n"
        f"`ADMIN_USER_ID={user.id}`\n\n"
        f"Или установите в `bot/config.py`:\n"
        f"`ADMIN_USER_ID = os.getenv(\"ADMIN_USER_ID\", \"{user.id}\")`\n\n"
        f"После этого перезапустите бота.",
        parse_mode='Markdown'
    )

# Команда для добавления администратора
async def addadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавляет нового администратора (только для существующих админов)"""
    user_id = update.effective_user.id
    
    # Проверка прав администратора
    if not await is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    
    # Получаем аргументы команды
    if not context.args:
        await update.message.reply_text(
            "📝 Использование: `/addadmin <telegram_id>` или `/addadmin @username`\n\n"
            "Примеры:\n"
            "`/addadmin 123456789`\n"
            "`/addadmin @username`",
            parse_mode='Markdown'
        )
        return
    
    try:
        arg = context.args[0]
        target_id = None
        target_user = None
        
        # Если это username (начинается с @)
        if arg.startswith('@'):
            target_username = arg[1:]  # Убираем @
            target_user = await get_user_by_username(target_username)
            if not target_user:
                await update.message.reply_text(f"❌ Пользователь @{target_username} не найден в базе данных.")
                return
            target_id = target_user.telegram_id
        else:
            # Это числовой ID
            target_id = int(arg)
            target_user = await get_user_by_telegram_id(target_id)
            if not target_user:
                await update.message.reply_text(f"❌ Пользователь с ID {target_id} не найден в базе данных.")
                return
        
        # Проверяем, не является ли уже администратором
        if await check_bot_admin_exists(target_id):
            await update.message.reply_text("⚠️ Этот пользователь уже является администратором.")
            return
        
        # Получаем текущего администратора
        current_admin_user = await get_user_by_telegram_id(user_id)
        
        # Создаем запись администратора
        await create_bot_admin(target_user, target_id, current_admin_user)
        
        await update.message.reply_text(
            f"✅ Администратор успешно добавлен!\n\n"
            f"👤 Пользователь: {target_user}\n"
            f"🆔 ID: {target_id}\n"
            f"➕ Добавлен: {update.effective_user.first_name}"
        )
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID. Используйте числовой ID или @username.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

# Команда для удаления администратора
async def removeadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаляет администратора (только для существующих админов)"""
    user_id = update.effective_user.id
    
    # Проверка прав администратора
    if not await is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    
    # Получаем аргументы команды
    if not context.args:
        await update.message.reply_text(
            "📝 Использование: `/removeadmin <telegram_id>` или `/removeadmin @username`\n\n"
            "Примеры:\n"
            "`/removeadmin 123456789`\n"
            "`/removeadmin @username`",
            parse_mode='Markdown'
        )
        return
    
    try:
        arg = context.args[0]
        target_id = None
        
        # Если это username
        if arg.startswith('@'):
            target_username = arg[1:]
            target_user = await get_user_by_username(target_username)
            if not target_user:
                await update.message.reply_text(f"❌ Пользователь @{target_username} не найден.")
                return
            target_id = target_user.telegram_id
        else:
            target_id = int(arg)
        
        # Проверяем, является ли администратором
        admin = await get_bot_admin(target_id)
        if not admin:
            await update.message.reply_text("❌ Этот пользователь не является администратором.")
            return
        
        # Не позволяем удалить самого себя
        if target_id == user_id:
            await update.message.reply_text("⚠️ Вы не можете удалить самого себя.")
            return
        
        # Деактивируем администратора
        await deactivate_bot_admin(admin)
        
        await update.message.reply_text(
            f"✅ Администратор удален!\n\n"
            f"👤 Пользователь: {admin.user}\n"
            f"🆔 ID: {target_id}"
        )
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID. Используйте числовой ID или @username.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

# Команда для просмотра списка администраторов
async def listadmins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список всех администраторов"""
    user_id = update.effective_user.id
    
    # Проверка прав администратора
    if not await is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    
    admins = await get_all_bot_admins()
    
    if not admins:
        await update.message.reply_text("📋 Список администраторов пуст.")
        return
    
    message = "👥 Список администраторов:\n\n"
    for idx, admin in enumerate(admins, 1):
        added_by_text = f" (добавлен: {admin.added_by})" if admin.added_by else ""
        message += f"{idx}. {admin.user}\n   🆔 {admin.telegram_id}{added_by_text}\n\n"
    
    await update.message.reply_text(message)

async def post_init(application: Application):
    # Кнопка меню слева от поля ввода — всегда актуальный домен
    try:
        await application.bot.set_chat_menu_button(
            menu_button={
                "type": "web_app",
                "text": "Играть",
                "web_app": {"url": WEBAPP_URL},
            }
        )
        await application.bot.set_my_commands([
            ("start", "Открыть игру"),
        ])
    except Exception:
        logging.exception("Не удалось обновить кнопку меню/команды")


# ──────────────────────────────────────────────────────────────────────────────
# Расширенные админ-команды из minimal_bot.py:
# /broadcast, /finduser (+ кнопки пополнения/списания), /burn, /market_open,
# /market_close, /stata. Права проверяются той же функцией is_admin, что и
# у остальных админ-команд (ADMIN_USER_ID из .env + таблица BotAdmin).
# ──────────────────────────────────────────────────────────────────────────────
import minimal_bot as _ext
from telegram.ext import CallbackQueryHandler

_ext._is_admin = is_admin  # вместо старой проверки из minimal_bot, которая пускала всех
import broadcasts
_ext._webapp_url = lambda tg_id, ref=None: play_webapp_url(tg_id, {"ref": ref} if ref else None)


def _has_admin_state(user_id):
    return (
        user_id in _ext.BROADCAST_STATES
        or user_id in _ext.ADMIN_STATES
        or user_id in _ext.BURN_STATES
    )


async def route_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Если админ в процессе рассылки / ввода суммы / сжигания — передаём в обработчик minimal_bot."""
    user_id = update.effective_user.id
    if _has_admin_state(user_id) and await is_admin(user_id):
        if user_id in _ext.BROADCAST_STATES:
            # рассылка с сохранением отправленных сообщений (чтобы их можно было удалить)
            _ext.BROADCAST_STATES.pop(user_id, None)
            user_ids = await _ext.db_get_all_user_ids()
            await broadcasts.send_broadcast(update, context, user_ids)
            return
        await _ext.text_router(update, context)
        return
    if update.message and update.message.text:
        await handle_message(update, context)


ADMIN_HELP = (
    "Команды админа:\n"
    "/finduser <id или @username> — найти пользователя, изменить баланс\n"
    "/broadcast — рассылка всем (следующим сообщением текст или фото)\n"
    "/delbroadcast — удалить последнюю рассылку у всех (в течение 48 часов)\n"
    "/burn — сжечь FL\n"
    "/market_open, /market_close — открыть / закрыть P2P-рынок\n"
    "/stata — статистика по поливу\n"
    "/myid — ваш ID\n"
    "/addadmin, /removeadmin, /listadmins — админы бота\n"
    "/tyrnir — начать турнир\n"
    "/priz — завершить турнир и выдать призы"
)


async def delbroadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await broadcasts.delbroadcast_command(update, context, is_admin)


async def delbroadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await broadcasts.delbroadcast_callback(update, context, is_admin)


async def help_command_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await help_command(update, context)
    if await is_admin(update.effective_user.id):
        await update.message.reply_text(ADMIN_HELP)


def build_application():
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command_full))
    application.add_handler(CommandHandler("play", play_command))
    application.add_handler(CommandHandler("ref", ref_command))
    application.add_handler(CommandHandler("myid", myid_command))
    application.add_handler(CommandHandler("addadmin", addadmin_command))
    application.add_handler(CommandHandler("removeadmin", removeadmin_command))
    application.add_handler(CommandHandler("listadmins", listadmins_command))
    application.add_handler(CommandHandler("tyrnir", tyrnir_command))
    application.add_handler(CommandHandler("priz", priz_command))
    application.add_handler(CommandHandler("broadcast", _ext.broadcast_command))
    application.add_handler(CommandHandler("delbroadcast", delbroadcast_command))
    application.add_handler(CallbackQueryHandler(delbroadcast_callback, pattern=r"^delbc_(yes|no)_"))
    application.add_handler(CommandHandler("finduser", _ext.finduser_command))
    application.add_handler(CommandHandler("burn", _ext.burn_command))
    application.add_handler(CommandHandler("market_open", _ext.market_open_command))
    application.add_handler(CommandHandler("market_close", _ext.market_close_command))
    application.add_handler(CommandHandler("stata", _ext.stata_command))
    application.add_handler(CallbackQueryHandler(_ext.callback_handler, pattern=r"^(addfl|subfl|addton|subton)_"))
    application.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, route_message))
    return application


async def _run():
    application = build_application()
    logging.info("Бот запущен!")
    print("✅ Бот успешно запущен и готов к работе!")
    print(f"✨ URL веб-приложения: {WEBAPP_URL}")
    async with application:
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        # держим процесс живым
        await asyncio.Event().wait()


def main():
    import asyncio
    print_config_info()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
