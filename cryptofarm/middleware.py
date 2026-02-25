from django.utils import translation
from users.models import User as TelegramUser


class TelegramFrameMiddleware:
    """
    Разрешает встраивание в iframe для Telegram Mini Apps (web.telegram.org, t.me).
    Заменяет X-Frame-Options: DENY на CSP frame-ancestors.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # Разрешаем Telegram Web, десктоп и мобильные приложения
        csp = "frame-ancestors 'self' https://web.telegram.org https://telegram.org https://t.me https://*.telegram.org;"
        response["Content-Security-Policy"] = csp
        response.pop("X-Frame-Options", None)  # убираем DENY, CSP имеет приоритет
        return response


class TelegramLanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tg_id = request.GET.get("tg_id") or request.session.get("telegram_id")
        if tg_id:
            try:
                u = TelegramUser.objects.only("language").get(telegram_id=int(tg_id))
                lang = (u.language or "ru").lower()
                if lang in ("ru", "en"):
                    translation.activate(lang)
                    request.LANGUAGE_CODE = lang
            except Exception:
                pass

        response = self.get_response(request)
        translation.deactivate()
        return response
