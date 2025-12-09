from telegram import Bot
from django.conf import settings
import logging
import traceback

logger = logging.getLogger(__name__)

def notify(user, text):
    # Проверка пользователя
    if not user:
        logger.error("Попытка отправить уведомление несуществующему пользователю")
        return False
        
    # Попробуем отправить уведомление через Telegram
    try:
        if user.tg_id:
            # Проверяем наличие токена
            if not settings.TG_BOT_TOKEN:
                logger.error("TG_BOT_TOKEN не настроен в settings")
                return False
                
            # Отправляем сообщение
            Bot(token=settings.TG_BOT_TOKEN).send_message(chat_id=user.tg_id, text=text)
            logger.info(f"Успешная отправка уведомления пользователю #{user.id} с tg_id {user.tg_id}")
            return True
    except Exception as e:
        logger.error(f"Ошибка отправки Telegram уведомления: {str(e)}")
        logger.debug(f"Детали ошибки: {traceback.format_exc()}")
    
    # SMS fallback - этот код нужно заменить на реальный SMS-провайдер
    try:
        if hasattr(settings, 'SMS_ENABLED') and settings.SMS_ENABLED and user.phone:
            # Пример интеграции с SMS API
            # sms_service.send(user.phone, text)
            logger.info(f"SMS отправлено на {user.phone}: {text}")
            return True
    except Exception as e:
        logger.error(f"Ошибка отправки SMS: {str(e)}")
        logger.debug(f"Детали ошибки: {traceback.format_exc()}")
    
    # Debug fallback - выводим в консоль/лог
    if settings.DEBUG:
        print(f"[NOTIFICATION] to user #{user.id}: {text}")
    
    return False
