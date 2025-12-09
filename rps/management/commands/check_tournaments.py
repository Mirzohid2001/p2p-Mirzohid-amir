"""
Команда для проверки и автоматической остановки турниров
Запускать через cron каждые 5 минут: */5 * * * * cd /path/to/project && python manage.py check_tournaments
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from rps.models import Tournament
import os
import sys
import django

# Настройка Django для использования в команде
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cryptofarm.settings')
django.setup()

try:
    from telegram import Bot
    from bot.config import BOT_TOKEN, ADMIN_USER_ID
    TELEGRAM_AVAILABLE = True
except:
    TELEGRAM_AVAILABLE = False


class Command(BaseCommand):
    help = 'Проверяет и автоматически останавливает завершенные турниры'

    def handle(self, *args, **options):
        # Ищем активные турниры, которые должны быть завершены
        active_tournaments = Tournament.objects.filter(
            status='active',
            end_date__lte=timezone.now()
        )
        
        for tournament in active_tournaments:
            tournament.status = 'completed'
            tournament.save()
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Турнир #{tournament.id} автоматически завершен'
                )
            )
            
            # Отправляем уведомление администратору (как в ТЗ)
            if TELEGRAM_AVAILABLE and ADMIN_USER_ID:
                try:
                    bot = Bot(token=BOT_TOKEN)
                    message = "🏆 Tournament stopped, counting results."
                    bot.send_message(chat_id=ADMIN_USER_ID, text=message)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Уведомление отправлено администратору'
                        )
                    )
                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(
                            f'Не удалось отправить уведомление: {e}'
                        )
                    )

