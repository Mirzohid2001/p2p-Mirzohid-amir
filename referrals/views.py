import requests
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from .models import Referral, ReferralBonus, Task, TaskCompletion
from django.db import models
from django.db.models import Sum
from decimal import Decimal
from .utils import get_telegram_user
from users.services import build_referral_link


def referral_page(request):
    ...
    tasks = Task.objects.filter(is_active=True)
    ...
    return render(request, "referral.html", {
        "tasks": tasks,
    })

def referral_program(request):
    """
    Отображает детали реферальной программы пользователя:
    - количество приглашенных друзей
    - заработанные бонусы
    - список рефералов
    - прогресс к следующему уровню
    """
    user = request.user
    
    # Получаем данные по рефералам
    direct_referrals = Referral.objects.filter(inviter=user).select_related('invited')
    referral_count = direct_referrals.count()
    
    # Получаем информацию о бонусах
    referral_rewards = Referral.objects.filter(inviter=user).aggregate(
        s=Sum('bonus_cf')
    )['s'] or Decimal('0')

    # Вычисляем прогресс до следующего уровня
    next_bonus_step = 5
    current_level = referral_count // next_bonus_step
    next_badge = (current_level + 1) * next_bonus_step
    referal_to_next_badge = max(0, next_badge - referral_count)
    
    # Формируем сообщения для пользователя
    main_stats = f"Вы пригласили <b>{referral_count}</b> друзей и заработали <b>{referral_rewards} CF</b>!"
    if referal_to_next_badge == 0:
        motivation_text = "Поздравляем! Вы получили новый бейдж или бонус! 🏅"
    else:
        motivation_text = f"Пригласите ещё <b>{referal_to_next_badge}</b> друзей — получите <b>50 CF бонус</b> и новый бейдж! 🚀"
    
    # Формируем реферальную ссылку
    if user.telegram_id:
        referral_link = build_referral_link(user.telegram_id)
    else:
        referral_link = None
    
    # Подготавливаем данные о рефералах
    referrals_data = []
    for referral in direct_referrals:
        invited_user = referral.invited
        referrals_data.append({
            'user': invited_user,
            'username': invited_user.username,
            'first_name': invited_user.first_name,
            'created_at': referral.date_joined,
            'bonus': referral.bonus_cf
        })
    
    # Добавляем текущий уровень и прогресс
    level_progress_raw = (referral_count % next_bonus_step) / next_bonus_step * 100
    
    # Округляем до ближайшего десятка для CSS-класса
    progress_class = int(round(level_progress_raw / 10) * 10)
    if progress_class > 100:
        progress_class = 100
    elif progress_class < 0:
        progress_class = 0
        
    # Форматированное значение для отображения
    level_progress = '{:.1f}'.format(level_progress_raw)
    tasks = Task.objects.filter(is_active=True)
    completed_task_ids = set(TaskCompletion.objects.filter(user=user, task__in=tasks).values_list('task_id', flat=True))

    
    context = {
        'referral_code': user.referral_code,  # Добавляем сам код
        'referral_count': referral_count,
        'referral_rewards': referral_rewards,
        'main_stats': main_stats,
        'motivation_text': motivation_text,
        'referral_link': referral_link,
        'user': user,
        'referrals': referrals_data,  # Добавляем список рефералов
        'current_level': current_level,
        'level_progress': level_progress,
        'progress_class': progress_class,  # Для CSS-класса прогресса
        'referals_to_next_level': referal_to_next_badge,
        'next_badge': next_badge,
        'tasks': tasks,
        'completed_task_ids': completed_task_ids,

    }
    return render(request, 'referral/index.html', context)

TELEGRAM_BOT_TOKEN = '7279695557:AAGDcy3GhWdKELn1gxZS71Pokb2N7EYHulM'
def is_user_in_channel(telegram_id, channel_username):
    # Проверяем подписку через Telegram Bot API
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getChatMember"
    params = {
        'chat_id': f"@{channel_username}",
        'user_id': telegram_id
    }
    r = requests.get(url, params=params)
    data = r.json()
    if data.get("ok") and data.get("result", {}).get("status") in ("member", "administrator", "creator"):
        return True
    return False


@csrf_exempt
def check_task(request, task_id):
    user = get_telegram_user(request)
    if not user:
        return JsonResponse({'status': 'error', 'msg': 'Авторизуйтесь!'}, status=403)

    try:
        task = Task.objects.get(id=task_id, is_active=True)
    except Task.DoesNotExist:
        return JsonResponse({'status': 'error', 'msg': 'Задание не найдено!'}, status=404)

    if TaskCompletion.objects.filter(user=user, task=task).exists():
        return JsonResponse({'status': 'error', 'msg': 'Вы уже выполнили это задание!'})

    if task.type == "tg_channel":
        if not task.channel_username:
            return JsonResponse({'status': 'error', 'msg': 'У задания не указан канал!'})
        if not user.telegram_id:
            return JsonResponse({'status': 'error', 'msg': 'Свяжите Telegram-аккаунт!'})
        if not is_user_in_channel(user.telegram_id, task.channel_username):
            return JsonResponse({'status': 'error', 'msg': 'Вы не подписаны на канал!'})

    user.cf_balance += task.reward_fl
    user.save(update_fields=['cf_balance'])
    TaskCompletion.objects.create(user=user, task=task)
    return JsonResponse({'status': 'success', 'reward': task.reward_fl, 'msg': f'Зачислено {task.reward_fl} FL!'})
