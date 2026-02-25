# users/views.py
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.crypto import get_random_string

from cryptofarm import settings
from cryptofarm.utils.telegram import validate_telegram_data, extract_user_data, validate_telegram_login_widget
from trees.views import get_current_user
from .models import User, TonDepositRequest
from trees.models import Tree
from referrals.models import Referral, ReferralBonus
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.utils import translation
from users.models import User as TelegramUser
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt


def _is_ngrok_request(request):
    host = request.get_host()
    return "ngrok" in host.lower()


def telegram_login(request):
    # 1) Обработка callback от Telegram Login Widget (Chrome, обычный браузер)
    widget_hash = request.GET.get("hash")
    if widget_hash:
        bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", None) or getattr(settings, "TG_BOT_TOKEN", None)
        if bot_token:
            data = {k: v for k, v in request.GET.items() if k != "hash"}
            data["hash"] = widget_hash
            if validate_telegram_login_widget(data, bot_token):
                tg_id_int = int(request.GET.get("id", 0))
                _create_or_login_user(request, tg_id_int, request.GET)
                return redirect("home")
        auth_url = request.build_absolute_uri(request.path)
        bot_username = getattr(settings, "TELEGRAM_BOT_USERNAME", None) or getattr(settings, "BOT_USERNAME", None) or "OxiriP2P_bot"
        return render(request, "users/telegram_login.html", {
            "error": "Ошибка проверки авторизации. Попробуйте снова.",
            "bot_username": bot_username,
            "auth_url": auth_url,
        })

    # 2) Обработка tg_id от WebApp (Telegram / Telegram Web)
    tg_id = request.GET.get("tg_id")
    if not tg_id:
        auth_url = request.build_absolute_uri(request.path)
        bot_username = getattr(settings, "TELEGRAM_BOT_USERNAME", None) or getattr(settings, "BOT_USERNAME", None) or "OxiriP2P_bot"
        # ngrok + iframe (Telegram Web): первый запрос может не иметь header — отдаём loader
        if _is_ngrok_request(request) and request.headers.get("ngrok-skip-browser-warning") != "true":
            from django.http import HttpResponse
            import json
            fetch_url = request.build_absolute_uri(request.get_full_path())
            loader_html = """<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Загрузка...</title></head><body style="margin:0;display:flex;align-items:center;justify-content:center;min-height:100vh;background:#6B75E6;color:white;font-family:sans-serif"><p>Загрузка...</p></body><script>
(function(){
  var url = """ + json.dumps(fetch_url) + """;
  fetch(url, { headers: { "ngrok-skip-browser-warning": "true" } })
    .then(function(r){ return r.text(); })
    .then(function(html){
      document.open();
      document.write(html);
      document.close();
    })
    .catch(function(){ document.body.innerHTML = "<p>Ошибка загрузки. Попробуйте «Открыть в браузере» в меню Telegram.</p>"; });
})();
</script></html>"""
            return HttpResponse(loader_html)
        return render(request, "users/telegram_login.html", {
            "bot_username": bot_username,
            "auth_url": auth_url,
        })

    try:
        tg_id_int = int(tg_id)
    except ValueError:
        return redirect("home")

    _create_or_login_user(request, tg_id_int)
    home_url = request.build_absolute_uri("/") + f"?tg_id={tg_id_int}"
    from django.http import HttpResponse
    # meta refresh + ссылка — form.submit() может не сработать в Telegram Web iframe
    html = f'''<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="0;url={home_url}">
<title>Вход...</title></head>
<body style="margin:0;display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;background:#6B75E6;color:white;font-family:sans-serif;padding:20px;text-align:center">
<p style="margin-bottom:20px">Вход выполнен!</p>
<p style="font-size:14px;opacity:0.9">Переход в игру…</p>
<a href="{home_url}" style="margin-top:24px;display:inline-block;background:rgba(255,255,255,0.3);color:white;padding:12px 24px;border-radius:12px;text-decoration:none;font-weight:600">Нажмите, если не перешли</a>
</body></html>'''
    return HttpResponse(html)


@csrf_exempt
@require_http_methods(["POST"])
def telegram_auth_initdata(request):
    """
    Вход по initData из WebApp. POST с init_data.
    Для Telegram Web — meta refresh вместо 302, чтобы редирект работал в iframe.
    """
    from django.http import HttpResponse
    init_data = request.POST.get("init_data", "")
    bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
    if not bot_token or bot_token == "YOUR_BOT_TOKEN" or not init_data:
        return HttpResponse(
            "<html><body><p>Ошибка: нет init_data или токена</p></body></html>",
            status=400,
        )
    validated = validate_telegram_data(init_data, bot_token)
    if not validated:
        return HttpResponse(
            "<html><body><p>Ошибка проверки данных</p></body></html>",
            status=403,
        )
    user_data = extract_user_data(validated)
    if not user_data or not user_data.get("telegram_id"):
        return HttpResponse(
            "<html><body><p>Нет данных пользователя</p></body></html>",
            status=400,
        )
    tg_id_int = user_data["telegram_id"]
    _create_or_login_user(request, tg_id_int, user_data)
    home_url = request.build_absolute_uri("/")
    # HTML с meta refresh — надёжнее в Telegram WebView чем 302
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta http-equiv="refresh" content="0;url={home_url}"><title>Вход...</title></head><body><p>Вход выполнен. <a href="{home_url}">Перейти</a></p></body></html>"""
    resp = HttpResponse(html)
    return resp


def _create_or_login_user(request, tg_id_int, widget_data=None):
    """Создаёт или находит пользователя и записывает в сессию."""
    defaults = {
        "username": "",
        "first_name": "",
        "last_name": "",
        "photo_url": "",
        "cf_balance": 100.00,
        "ton_balance": 0.00
    }
    if widget_data:
        defaults["username"] = widget_data.get("username", "") or ""
        defaults["first_name"] = widget_data.get("first_name", "") or ""
        defaults["last_name"] = widget_data.get("last_name", "") or ""
        defaults["photo_url"] = widget_data.get("photo_url", "") or ""

    user, created = User.objects.get_or_create(
        telegram_id=tg_id_int,
        defaults=defaults
    )

    if created and not widget_data:
        Tree.objects.create(user=user, type="CF")
        user.cf_balance = 100
        user.save()
        ref_code = request.GET.get("ref")
        if ref_code:
            try:
                ref_id_int = int(ref_code)
                referrer = User.objects.filter(telegram_id=ref_id_int).first()
            except (ValueError, User.DoesNotExist):
                referrer = None

            if referrer and referrer != user:

                already_has_ref = Referral.objects.filter(invited=user).exists()
                if not already_has_ref:
                    user.referred_by = referrer
                    user.save()

                    referral = Referral.objects.create(
                        inviter=referrer,
                        invited=user,
                        bonus_cf=10
                    )
                    ReferralBonus.objects.create(
                        referral=referral,
                        bonus_type="signup",
                        amount=10,
                        description=f"Бонус за регистрацию {user}"
                    )
                    referrer.cf_balance += 10
                    referrer.save()
    elif created and widget_data:
        Tree.objects.create(user=user, type="CF")
        user.cf_balance = 100
        user.save()
        if request.GET.get("ref"):
            try:
                ref_id_int = int(request.GET.get("ref"))
                referrer = User.objects.filter(telegram_id=ref_id_int).first()
                if referrer and referrer != user and not Referral.objects.filter(invited=user).exists():
                    user.referred_by = referrer
                    user.save()
                    referral = Referral.objects.create(inviter=referrer, invited=user, bonus_cf=10)
                    ReferralBonus.objects.create(referral=referral, bonus_type="signup", amount=10, description=f"Бонус за регистрацию {user}")
                    referrer.cf_balance += 10
                    referrer.save()
            except (ValueError, TypeError):
                pass
    else:
        if not Tree.objects.filter(user=user).exists():
            Tree.objects.create(user=user, type="CF")
        if widget_data:
            user.username = widget_data.get("username", "") or user.username
            user.first_name = widget_data.get("first_name", "") or user.first_name
            user.last_name = widget_data.get("last_name", "") or user.last_name
            user.photo_url = widget_data.get("photo_url", "") or user.photo_url
            user.save()

    request.session["telegram_id"] = tg_id_int


@require_POST
def set_lang_and_django(request):
    lang = request.POST.get("language", "ru")
    next_url = request.POST.get("next") or "/"

    tg_id = request.GET.get("tg_id") or request.session.get("telegram_id")
    if tg_id:
        TelegramUser.objects.filter(telegram_id=int(tg_id)).update(language=lang)

    translation.activate(lang)
    resp = redirect(next_url)
    resp.set_cookie("django_language", lang)  # важно для Django i18n
    return resp

def profile_view(request):
    telegram_id = request.session.get("telegram_id") or request.GET.get("telegram_id")
    if not telegram_id:
        return redirect('/telegram_login/')

    user = get_object_or_404(User, telegram_id=telegram_id)

    cf_balance = user.cf_balance
    ton_balance = user.ton_balance
    trees = user.trees.all() if hasattr(user, 'trees') else []
    referral_code = user.referral_code
    photo_url = user.photo_url

    # Referal statistika va ro‘yxat
    direct_referrals = Referral.objects.filter(inviter=user)
    referral_count = direct_referrals.count()
    bonuses = ReferralBonus.objects.filter(referral__inviter=user)
    referral_rewards = sum(b.amount for b in bonuses)
    referrals_info = [{
        'username': r.invited.username,
        'first_name': r.invited.first_name,
        'last_name': r.invited.last_name,
        'joined': r.date_joined,
    } for r in direct_referrals]

    context = {
        "user": user,
        "cf_balance": cf_balance,
        "ton_balance": ton_balance,
        "trees": trees,
        "referral_code": referral_code,
        "photo_url": photo_url,
        "referral_count": referral_count,
        "referral_rewards": referral_rewards,
        "referrals_info": referrals_info,
        "recipient_address": "UQAaSqEaBNAXz4gz7oJvrYXLaKXGaoUcxXFKR4rdW8KPwzLp"
    }
    return render(request, "users/profile.html", context)

def deposit_ton(request):
    user = get_current_user(request)  # или request.user
    if not user:
        messages.error(request, "Сначала авторизуйтесь!")
        return redirect("telegram_login")

    if request.method == "POST":
        try:
            amount = float(request.POST.get("amount", 0))
        except (TypeError, ValueError):
            messages.error(request, "Некорректная сумма")
            return redirect("profile")

        if amount <= 0:
            messages.error(request, "Сумма должна быть больше 0")
            return redirect("profile")


        memo = f"p2p_{user.telegram_id}_{get_random_string(6)}_{amount:.4f}"
        ton_wallet_address = settings.PROJECT_TON_WALLET  # пропиши свой адрес
        deeplink = f"https://t.me/wallet?startapp=ton_transfer_{ton_wallet_address}_{amount}"

        TonDepositRequest.objects.create(
            user=user,
            amount=amount,
            memo=memo,
        )

        messages.info(request,
            f"Переведите <b>{amount} TON</b> на адрес <code>{ton_wallet_address}</code> "
            f"с комментарием <b>{memo}</b>.<br>"
            f"Это важно — иначе пополнение не зачтётся.<br>"
            f"<a href='{deeplink}' target='_blank'>Открыть Telegram Wallet</a>"
        )
        return redirect("profile")
    return redirect("profile")

@csrf_exempt
def save_wallet(request):
    if request.method == "POST":
        telegram_id = request.session.get("telegram_id")
        address = request.POST.get("address")
        if not telegram_id or not address:
            return JsonResponse({"error": "No session or address"}, status=400)
        user = User.objects.filter(telegram_id=telegram_id).first()
        if user:
            user.ton_wallet = address
            user.save()
            return JsonResponse({"success": True})
        return JsonResponse({"error": "No user"}, status=404)
    return JsonResponse({"error": "Bad method"}, status=405)


def get_ton_balance(request):
    telegram_id = request.session.get("telegram_id")
    if not telegram_id:
        return JsonResponse({"error": "no session"}, status=401)

    user = User.objects.filter(telegram_id=telegram_id).first()
    if not user:
        return JsonResponse({"error": "no user"}, status=404)

    return JsonResponse({"balance": f"{user.ton_balance:.8f}"})
