"""
Команда для очистки истекших игр
Запускать через cron каждые 5 минут
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from rps.models import Game
from django.db import transaction


class Command(BaseCommand):
    help = 'Очищает истекшие игры и возвращает ставки игрокам'

    def handle(self, *args, **options):
        # Ищем истекшие активные игры
        expired_games = Game.objects.filter(
            status__in=['waiting', 'betting', 'playing'],
            expires_at__lte=timezone.now()
        )
        
        count = 0
        for game in expired_games:
            with transaction.atomic():
                # Возвращаем ставки игрокам
                if game.player1:
                    game.player1.cf_balance += game.player1_bet
                    game.player1.save(update_fields=['cf_balance'])
                
                if game.player2:
                    game.player2.cf_balance += game.player2_bet
                    game.player2.save(update_fields=['cf_balance'])
                elif game.is_bot_game:
                    # Возвращаем баланс бота в пул
                    from rps.models import BotPool
                    bot_pool = BotPool.get_pool()
                    bot_pool.return_balance(game.player2_bet)
                
                # Отменяем игру
                game.status = 'cancelled'
                game.save()
                count += 1
        
        if count > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Отменено истекших игр: {count}'
                )
            )

