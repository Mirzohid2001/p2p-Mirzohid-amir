"""
Единый файл запуска Telegram-бота с поддержкой Mini App
"""

import os
import sys
import logging
import dotenv
import django

from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# 1. Загрузка .env
dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(dotenv_path):
    dotenv.load_dotenv(dotenv_path)

# 2. Настройка Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crypto_backend.settings')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
django.setup()

# 3. Логгирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# 4. Переменные окружения
WEBAPP_URL = os.getenv('WEBAPP_URL', 'https://localhost:8000/')
BOT_TOKEN = os.getenv('TG_BOT_TOKEN')


# === Обработчики ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info(f"Пользователь {user.id} ({user.username}) запустил бота")

    # Проверяем, есть ли реферальный код
    ref_code = None
    if context.args and len(context.args) > 0:
        ref_code = context.args[0]
        logger.info(f"Получен реферальный код: {ref_code}")
        
        # Если есть реферальный код, передаем его в WebApp через параметр URL
        webapp_url = f"{WEBAPP_URL}?ref={ref_code}"
        logger.info(f"Формируем URL с реферальным кодом: {webapp_url}")
    else:
        webapp_url = WEBAPP_URL
        logger.info(f"Используем стандартный URL без реферального кода: {webapp_url}")

    # Кнопка запуска Mini App
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌿 Играть", web_app=WebAppInfo(url=webapp_url))]
    ])

    welcome_message = f"Привет, {user.first_name}! 👋\n\n"
    welcome_message += "Добро пожаловать в Crypto Farm!\n"
    
    if ref_code:
        welcome_message += f"Тебя пригласил пользователь с кодом: {ref_code}\n"
        welcome_message += "Вы оба получите бонус 50 CF при регистрации!\n\n"
    
    welcome_message += "Нажми на кнопку ниже, чтобы открыть игру:"

    await update.message.reply_text(
        welcome_message,
        reply_markup=keyboard
    )


async def handle_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message.web_app_data:
        data = update.effective_message.web_app_data.data
        await update.message.reply_text(f"📩 Получены данные из Mini App: {data}")


# === Запуск бота ===
def run_bot():
    if not BOT_TOKEN:
        logger.error("❌ TG_BOT_TOKEN не найден в .env")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))

    logger.info(f"🚀 Запуск бота с WebApp URL: {WEBAPP_URL}")
    app.run_polling()


if __name__ == "__main__":
    print("✅ Бот запускается...")
    run_bot()