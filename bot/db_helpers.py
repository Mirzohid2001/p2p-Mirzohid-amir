"""
Вспомогательные функции для работы с базой данных в асинхронном контексте
"""
from asgiref.sync import sync_to_async
from users.models import User
from rps.models import BotAdmin, Tournament, TournamentParticipant
from django.utils import timezone
from datetime import timedelta


@sync_to_async
def check_is_admin(user_id, admin_user_id):
    """Проверяет, является ли пользователь администратором"""
    if admin_user_id and str(user_id) == str(admin_user_id):
        return True
    return BotAdmin.is_admin(user_id)


@sync_to_async
def get_active_tournament():
    """Получает активный турнир"""
    return Tournament.objects.filter(status='active').first()


@sync_to_async
def create_tournament():
    """Создает новый турнир"""
    end_date = timezone.now() + timedelta(days=6)
    tournament = Tournament.objects.create(
        status='active',
        end_date=end_date
    )
    return tournament, end_date


@sync_to_async
def get_completed_tournament():
    """Получает завершенный турнир"""
    return Tournament.objects.filter(status='completed').first()


@sync_to_async
def complete_tournament(tournament):
    """Завершает турнир"""
    tournament.status = 'completed'
    tournament.save()
    return tournament


@sync_to_async
def get_tournament_top_10(tournament):
    """Получает топ-10 участников турнира"""
    # Получаем участников с предзагрузкой связанных объектов
    top_10_queryset = tournament.participants.select_related('user').order_by('-points')[:10]
    # Преобразуем QuerySet в список, чтобы избежать проблем с асинхронностью
    # И предзагружаем все связанные объекты
    return list(top_10_queryset)


@sync_to_async
def reward_participant(participant, reward_amount):
    """Выдает награду участнику"""
    participant.reward_amount = reward_amount
    participant.reward_received = True
    participant.user.cf_balance += reward_amount
    participant.user.save(update_fields=['cf_balance'])
    participant.points = 0
    participant.save(update_fields=['points', 'reward_amount', 'reward_received'])


@sync_to_async
def mark_tournament_rewarded(tournament):
    """Помечает турнир как награжденный"""
    tournament.status = 'rewarded'
    tournament.reward_date = timezone.now()
    tournament.save()


@sync_to_async
def get_user_by_username(username):
    """Получает пользователя по username"""
    try:
        return User.objects.get(username=username)
    except User.DoesNotExist:
        return None


@sync_to_async
def get_user_by_telegram_id(telegram_id):
    """Получает пользователя по telegram_id"""
    try:
        return User.objects.get(telegram_id=telegram_id)
    except User.DoesNotExist:
        return None


@sync_to_async
def check_bot_admin_exists(telegram_id):
    """Проверяет, существует ли администратор"""
    return BotAdmin.is_admin(telegram_id)


@sync_to_async
def create_bot_admin(user, telegram_id, added_by):
    """Создает запись администратора"""
    return BotAdmin.objects.create(
        user=user,
        telegram_id=telegram_id,
        added_by=added_by,
        is_active=True
    )


@sync_to_async
def get_bot_admin(telegram_id):
    """Получает администратора"""
    return BotAdmin.objects.filter(telegram_id=telegram_id, is_active=True).first()


@sync_to_async
def deactivate_bot_admin(admin):
    """Деактивирует администратора"""
    admin.is_active = False
    admin.save()


@sync_to_async
def get_all_bot_admins():
    """Получает всех активных администраторов"""
    # Получаем QuerySet и преобразуем в список внутри синхронной функции
    admins = BotAdmin.objects.filter(is_active=True).select_related('user', 'added_by')
    return list(admins)

