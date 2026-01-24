from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db import transaction
from django.db.models import Q, Subquery
from decimal import Decimal
from datetime import timedelta
import json
import random

from users.models import User
from .models import Tournament, TournamentParticipant, Game, GameQueue, BotPool
from .templatetags.mask import mask_last

# Таймаут на совершение хода: 10 секунд
MOVE_TIMEOUT_SECONDS = 10

# Список случайных имен для ботов
BOT_NAMES = [
    'Alex', 'Max', 'Sam', 'Jordan', 'Taylor', 'Casey', 'Morgan', 'Riley',
    'Avery', 'Quinn', 'Dakota', 'Sage', 'River', 'Phoenix', 'Skyler',
    'Cameron', 'Drew', 'Blake', 'Hayden', 'Reese', 'Parker', 'Finley',
    'Rowan', 'Emery', 'Kai', 'Logan', 'Jamie', 'Dylan', 'Aiden', 'Noah',
    'Ethan', 'Liam', 'Mason', 'Lucas', 'Oliver', 'Aria', 'Emma', 'Mia',
    'Sophia', 'Isabella', 'Olivia', 'Charlotte', 'Amelia', 'Harper',
    'Evelyn', 'Abigail', 'Emily', 'Elizabeth', 'Sofia', 'Avery', 'Ella'
]


def generate_bot_name():
    """Генерирует случайное имя для бота"""
    return random.choice(BOT_NAMES)


def _resolve_timeout_cancel(game: Game, inactive_user=None):
    """Отменяет игру по таймауту, если игрок не сделал ход. Возвращает ставки."""
    game.status = 'cancelled'
    game.finished_at = timezone.now()
    
    # Возвращаем ставки обоим игрокам
    if game.player1:
        game.player1.cf_balance += game.player1_bet
        game.player1.save(update_fields=['cf_balance'])
    
    if game.player2:
        game.player2.cf_balance += game.player2_bet
        game.player2.save(update_fields=['cf_balance'])
    elif game.is_bot_game:
        # Возвращаем баланс бота в пул
        from .models import BotPool
        bot_pool = BotPool.get_pool()
        bot_pool.return_balance(game.player2_bet)
    
    game.save()
    return game



def rps_home(request):
    """Главная страница игры"""
    user = request.user
    active_tournament = Tournament.objects.filter(status='active').first()
    
    # Получаем статистику пользователя
    user_stats = {
        'games_played': Game.objects.filter(
            Q(player1=user) | Q(player2=user),
            status='finished'
        ).count(),
        'wins': Game.objects.filter(winner=user).count(),
        'draws': Game.objects.filter(
            Q(player1=user) | Q(player2=user),
            result='draw',
            status='finished'
        ).count(),
    }
    user_stats['losses'] = user_stats['games_played'] - user_stats['wins'] - user_stats['draws']
    
    # Статистика турнира
    tournament_stats = None
    if active_tournament:
        participant = TournamentParticipant.objects.filter(
            tournament=active_tournament,
            user=user
        ).first()
        if participant:
            rank = active_tournament.get_participant_rank(user)
            tournament_stats = {
                'points': participant.points,
                'rank': rank,
                'games_played': participant.games_played,
            }
    
    # Топ-10 турнира
    top_10 = []
    if active_tournament:
        top_10 = active_tournament.get_top_10()
    
    # Топ-5 игроков (общий рейтинг по всем играм)
    top_5_players = get_top_5_players()
    
    # Последние игры пользователя
    recent_games = Game.objects.filter(
        Q(player1=user) | Q(player2=user),
        status='finished'
    ).order_by('-finished_at')[:5]
    
    context = {
        'user': user,
        'user_stats': user_stats,
        'active_tournament': active_tournament,
        'tournament_stats': tournament_stats,
        'top_10': top_10,
        'top_5_players': top_5_players,
        'recent_games': recent_games,
    }
    
    return render(request, 'rps/home.html', context)


def get_top_5_players():
    """Получает топ-5 игроков по общему рейтингу"""
    from django.db.models import Count, Q
    
    # Получаем всех пользователей, которые играли
    all_users = User.objects.filter(
        Q(games_as_player1__status='finished') | Q(games_as_player2__status='finished')
    ).distinct()
    
    players_stats = []
    
    for user in all_users:
        # Игры где пользователь был player1
        games_as_p1 = Game.objects.filter(player1=user, status='finished')
        # Игры где пользователь был player2
        games_as_p2 = Game.objects.filter(player2=user, status='finished')
        
        total_games = games_as_p1.count() + games_as_p2.count()
        
        if total_games == 0:
            continue
        
        # Подсчитываем победы
        wins = Game.objects.filter(winner=user, status='finished').count()
        
        # Подсчитываем ничьи
        draws = Game.objects.filter(
            Q(player1=user, result='draw', status='finished') |
            Q(player2=user, result='draw', status='finished')
        ).count()
        
        losses = total_games - wins - draws
        win_rate = (wins / total_games * 100) if total_games > 0 else 0
        win_rate = round(win_rate, 1)  # Округляем до 1 знака после запятой
        
        players_stats.append({
            'user': user,
            'wins': wins,
            'losses': losses,
            'draws': draws,
            'total_games': total_games,
            'win_rate': win_rate,
        })
    
    # Сортируем по победам, затем по общему количеству игр
    players_stats.sort(key=lambda x: (x['wins'], x['total_games']), reverse=True)
    
    # Берем топ-5
    top_5 = players_stats[:5]
    
    # Добавляем ранги
    for idx, player in enumerate(top_5, 1):
        player['rank'] = idx
    
    return top_5


def rps_game(request, game_id=None):
    """Страница игры"""
    user = request.user
    
    if game_id:
        game = get_object_or_404(Game, id=game_id)
        
        # Проверяем, не истекла ли игра
        if game.expires_at and game.expires_at <= timezone.now() and game.status != 'finished':
            return redirect('rps:home')
        
        # Проверяем, что пользователь участвует в игре
        if game.is_bot_game:
            # Для игры с ботом проверяем только player1
            if game.player1 != user:
                return redirect('rps:home')
        else:
            # Для PvP проверяем обоих игроков
            if game.player1 != user and (not game.player2 or game.player2 != user):
                return redirect('rps:home')
    else:
        game = None
    
    # Определяем, является ли пользователь player1
    is_player1 = False
    if game:
        is_player1 = (game.player1 == user)
    
    context = {
        'user': user,
        'game': game,
        'is_player1': is_player1,
    }
    
    return render(request, 'rps/game.html', context)


@csrf_exempt
def api_search_game(request):
    """API для поиска игры"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    user = request.user
    
    try:
        data = json.loads(request.body)
        bet_amount = Decimal(str(data.get('bet_amount', 0)))
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid bet amount'}, status=400)
    
    # Проверяем доступные ставки
    valid_bets = [10, 50, 100, 500]
    if bet_amount not in valid_bets:
        return JsonResponse({'error': 'Invalid bet amount'}, status=400)
    
    # Проверяем баланс
    user.refresh_from_db()
    if user.cf_balance < bet_amount:
        return JsonResponse({'error': 'Недостаточно средств'}, status=400)
    
    # Проверяем активный турнир
    active_tournament = Tournament.objects.filter(status='active').first()
    

    expires_at = timezone.now() + timezone.timedelta(seconds=5)
    queue_item, created = GameQueue.objects.get_or_create(
        user=user,
        defaults={
            'bet_amount': bet_amount,
            'tournament': active_tournament,
            'expires_at': expires_at,
        }
    )
    
    if not created:
        queue_item.bet_amount = bet_amount
        queue_item.expires_at = expires_at
        queue_item.save()
    
    # Ищем подходящего противника с блокировкой строк для предотвращения race condition
    with transaction.atomic():
        active_players = Game.objects.filter(
            status__in=['waiting', 'betting', 'playing']
        )

        # Блокируем строки в очереди и исключаем игроков, уже находящихся в активной игре
        opponent_queue = GameQueue.objects.select_for_update().filter(
            ~Q(user=user),
            bet_amount=bet_amount,
            expires_at__gt=timezone.now()
        ).exclude(
            user__cf_balance__lt=bet_amount
        ).exclude(
            Q(user__in=Subquery(active_players.values('player1'))) |
            Q(user__in=Subquery(active_players.values('player2')))
        ).first()
        
        # Проверяем, не находится ли пользователь уже в активной игре
        active_game = Game.objects.filter(
            (Q(player1=user) | Q(player2=user)),
            status__in=['waiting', 'betting', 'playing']
        ).first()
        
        if active_game:
            # Пользователь уже в игре
            queue_item.delete()
            return JsonResponse({
                'success': True,
                'game_id': active_game.id,
                'opponent_found': True,
            })
        
        if opponent_queue:
            # Проверяем, не находится ли противник уже в игре
            opponent_active_game = Game.objects.filter(
                (Q(player1=opponent_queue.user) | Q(player2=opponent_queue.user)),
                status__in=['waiting', 'betting', 'playing']
            ).first()
            
            if opponent_active_game:
                # Противник уже в игре, удаляем его из очереди и продолжаем поиск
                opponent_queue.delete()
                return JsonResponse({
                    'success': True,
                    'game_id': None,
                    'opponent_found': False,
                    'searching': True,
                })
            
            # Нашли противника - создаем игру
            # Списываем ставки с балансов обоих игроков
            # Эти деньги временно "заморожены" в банке игры
            user.cf_balance -= bet_amount
            opponent_queue.user.cf_balance -= bet_amount
            user.save(update_fields=['cf_balance'])
            opponent_queue.user.save(update_fields=['cf_balance'])
            
            # Создаем игру с банком = сумма обеих ставок
            # Победитель получит весь банк, проигравший потеряет свою ставку
            from django.conf import settings
            expires_at = timezone.now() + timedelta(days=settings.GAME_SETTINGS.get('ORDER_EXPIRY', 3))
            
            game = Game.objects.create(
                player1=user,
                player2=opponent_queue.user,
                bet_amount=bet_amount,
                player1_bet=bet_amount,
                player2_bet=bet_amount,
                game_bank=bet_amount * 2,  # Банк = ставка игрока 1 + ставка игрока 2
                tournament=active_tournament,
                game_type='pvp',
                status='betting',
                expires_at=expires_at,
                move_timer_start=timezone.now(),  # старт таймера сразу после матчмейкинга
            )
            
            # Удаляем из очереди
            queue_item.delete()
            opponent_queue.delete()
            
            return JsonResponse({
                'success': True,
                'game_id': game.id,
                'opponent_found': True,
            })
    
    return JsonResponse({
        'success': True,
        'game_id': None,
        'opponent_found': False,
        'searching': True,
    })


@csrf_exempt
def api_make_move(request):
    """API для совершения хода"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    user = request.user
    
    try:
        data = json.loads(request.body)
        game_id = data.get('game_id')
        move = data.get('move')  # rock, paper, scissors
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid data'}, status=400)
    
    if move not in ['rock', 'paper', 'scissors']:
        return JsonResponse({'error': 'Invalid move'}, status=400)
    
    game = get_object_or_404(Game.objects.select_for_update(), id=game_id)
    
    # Обновляем объект из БД под блокировкой
    game.refresh_from_db()
    
    # Проверяем, не истекла ли игра
    if game.expires_at and game.expires_at <= timezone.now() and game.status != 'finished':
        # Возвращаем ставки и отменяем игру
        with transaction.atomic():
            if game.player1:
                game.player1.cf_balance += game.player1_bet
                game.player1.save(update_fields=['cf_balance'])
            if game.player2:
                game.player2.cf_balance += game.player2_bet
                game.player2.save(update_fields=['cf_balance'])
            elif game.is_bot_game:
                from .models import BotPool
                bot_pool = BotPool.get_pool()
                bot_pool.return_balance(game.player2_bet)
            game.status = 'cancelled'
            game.save()
        return JsonResponse({'error': 'Игра истекла, ставки возвращены'}, status=400)
    
    # Проверяем, что пользователь участвует в игре
    if game.player1_id != user.telegram_id and (not game.is_bot_game and game.player2_id != user.telegram_id):
        return JsonResponse({'error': 'Not your game'}, status=403)
    
    # Определяем, какой игрок делает ход
    is_player1 = (game.player1 == user)
    
    with transaction.atomic():
        if is_player1:
            game.player1_move = move
        else:
            game.player2_move = move
        
        # Если это первый ход в игре — стартуем таймер
        if not game.move_timer_start:
            game.move_timer_start = timezone.now()
        
        game.save()
        
        # Если это игра с ботом и пользователь сделал ход, бот делает ход автоматически
        if game.is_bot_game and not game.player2_move:
            # Бот делает ход (60% проигрывает, 40% выигрывает)
            bot_will_lose = random.random() < 0.6
            
            if bot_will_lose:
                # Бот проиграет - выбираем проигрышный ход
                if move == 'rock':
                    bot_move = 'scissors'
                elif move == 'paper':
                    bot_move = 'rock'
                else:  # scissors
                    bot_move = 'paper'
            else:
                # Бот выиграет - выбираем выигрышный ход
                if move == 'rock':
                    bot_move = 'paper'
                elif move == 'paper':
                    bot_move = 'scissors'
                else:  # scissors
                    bot_move = 'rock'
            
            game.player2_move = bot_move
            game.save()
        
        # Если оба игрока сделали ход, вычисляем результат
        if game.player1_move and game.player2_move:
            result = game.calculate_result()
            game.finish_game()
            
            return JsonResponse({
                'success': True,
                'game_finished': True,
                'result': result,
                'player1_move': game.player1_move,
                'player2_move': game.player2_move,
                'winner_id': game.winner.telegram_id if game.winner else None,
            })
        else:
            # Проверяем таймаут: если второй игрок не сделал ход за MOVE_TIMEOUT_SECONDS, фиксируем победу сделавшего ход
            if game.move_timer_start and game.status != 'finished':
                elapsed = (timezone.now() - game.move_timer_start).total_seconds()
                if elapsed >= MOVE_TIMEOUT_SECONDS:
                    if game.player1_move and not game.player2_move:
                        _resolve_timeout_win(game, game.player1)
                    elif game.player2_move and not game.player1_move:
                        _resolve_timeout_win(game, game.player2)
                    
                    return JsonResponse({
                        'success': True,
                        'game_finished': True,
                        'result': game.result,
                        'winner_id': game.winner.telegram_id if game.winner else None,
                    })
            
            return JsonResponse({
                'success': True,
                'game_finished': False,
                'move_registered': True,
            })


@csrf_exempt
def api_game_status(request, game_id):
    """API для получения статуса игры"""
    game = get_object_or_404(Game, id=game_id)
    user = request.user
    
    # Проверяем доступ
    if game.is_bot_game:
        # Для игры с ботом проверяем только player1
        if game.player1 != user:
            return JsonResponse({'error': 'Not your game'}, status=403)
    else:
        # Для PvP проверяем обоих игроков
        if game.player1 != user and (not game.player2 or game.player2 != user):
            return JsonResponse({'error': 'Not your game'}, status=403)
    
    # Если есть один ход и вышло время — завершаем по таймауту
    if game.status != 'finished' and game.status != 'cancelled' and game.move_timer_start:
        elapsed = (timezone.now() - game.move_timer_start).total_seconds()
        if elapsed >= MOVE_TIMEOUT_SECONDS:
            if game.player1_move and not game.player2_move:
                # Игрок 1 сделал ход, игрок 2 нет - отменяем игру
                _resolve_timeout_cancel(game, game.player2 if game.player2 else None)
            elif game.player2_move and not game.player1_move:
                # Игрок 2 сделал ход, игрок 1 нет - отменяем игру
                _resolve_timeout_cancel(game, game.player1)
            else:
                # Никто не сделал ход — отменяем игру
                _resolve_timeout_cancel(game, None)
    
    is_player1 = (game.player1 == user)
    
    response = {
        'game_id': game.id,
        'status': game.status,
        'player1_id': game.player1.telegram_id,
        'player2_id': game.player2.telegram_id if game.player2 else None,
        'is_bot_game': game.is_bot_game,
        'bot_name': game.bot_name if game.is_bot_game else None,
        'bet_amount': float(game.bet_amount),
        'game_bank': float(game.game_bank),
        'is_player1': is_player1,
        'player1_move': game.player1_move if (is_player1 or game.status == 'finished') else None,
        'player2_move': game.player2_move if (not is_player1 or game.status == 'finished' or game.is_bot_game) else None,
        'result': game.result,
        'winner_id': game.winner.telegram_id if game.winner else None,
    }
    
    return JsonResponse(response)


@csrf_exempt
def api_cancel_search(request):
    """API для отмены поиска игры"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    user = request.user
    
    # Удаляем пользователя из очереди
    GameQueue.objects.filter(user=user).delete()
    
    return JsonResponse({
        'success': True,
        'message': 'Поиск отменен',
    })


@csrf_exempt
def api_cancel_game(request):
    """API для отмены активной игры"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    user = request.user
    
    try:
        data = json.loads(request.body)
        game_id = data.get('game_id')
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid data'}, status=400)
    
    game = get_object_or_404(Game.objects.select_for_update(), id=game_id)
    
    # Проверяем, что пользователь участвует в игре
    is_player1 = (game.player1 == user)
    is_player2 = (game.player2 == user) if game.player2 else False
    
    if not is_player1 and not (is_player2 or game.is_bot_game):
        return JsonResponse({'error': 'Not your game'}, status=403)
    
    # Проверяем, что игра еще не завершена или отменена
    if game.status in ['finished', 'cancelled']:
        return JsonResponse({'error': 'Игра уже завершена или отменена'}, status=400)
    
    # Отменяем игру и возвращаем ставки
    with transaction.atomic():
        # Возвращаем ставку игрока 1
        if game.player1:
            game.player1.cf_balance += game.player1_bet
            game.player1.save(update_fields=['cf_balance'])
        
        # Возвращаем ставку игрока 2 или бота
        if game.player2:
            game.player2.cf_balance += game.player2_bet
            game.player2.save(update_fields=['cf_balance'])
        elif game.is_bot_game:
            from .models import BotPool
            bot_pool = BotPool.get_pool()
            bot_pool.return_balance(game.player2_bet)
        
        # Удаляем из очереди, если есть
        queue_users = [game.player1]
        if game.player2:
            queue_users.append(game.player2)
        GameQueue.objects.filter(user__in=queue_users).delete()
        
        # Отменяем игру
        game.status = 'cancelled'
        game.save()
    
    return JsonResponse({
        'success': True,
        'message': 'Игра отменена, ставки возвращены',
    })


@csrf_exempt
def api_connect_bot(request):
    """API для подключения бота после 10 секунд поиска"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    user = request.user
    
    try:
        data = json.loads(request.body)
        bet_amount = Decimal(str(data.get('bet_amount', 0)))
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid bet amount'}, status=400)
    
    # Проверяем баланс
    user.refresh_from_db()
    if user.cf_balance < bet_amount:
        return JsonResponse({'error': 'Недостаточно средств'}, status=400)
    
    # ВАЖНО: Проверяем, не находится ли пользователь уже в активной игре с реальным противником
    active_pvp_game = Game.objects.filter(
        (Q(player1=user) | Q(player2=user)),
        status__in=['waiting', 'betting', 'playing'],
        is_bot_game=False
    ).first()
    
    if active_pvp_game:
        # Пользователь уже в игре с реальным противником, возвращаем эту игру
        return JsonResponse({
            'success': True,
            'game_id': active_pvp_game.id,
            'opponent_found': True,
            'is_bot_game': False,
        })
    
    # Пытаемся найти реального противника прямо сейчас (повторная попытка перед ботом)
    with transaction.atomic():
        active_players = Game.objects.filter(
            status__in=['waiting', 'betting', 'playing']
        )

        opponent_queue = GameQueue.objects.select_for_update().filter(
            ~Q(user=user),
            bet_amount=bet_amount,
            expires_at__gt=timezone.now()
        ).exclude(
            user__cf_balance__lt=bet_amount
        ).exclude(
            Q(user__in=Subquery(active_players.values('player1'))) |
            Q(user__in=Subquery(active_players.values('player2')))
        ).first()

        if opponent_queue:
            # Списываем ставки с балансов обоих игроков
            user.cf_balance -= bet_amount
            opponent_queue.user.cf_balance -= bet_amount
            user.save(update_fields=['cf_balance'])
            opponent_queue.user.save(update_fields=['cf_balance'])

            # Создаем игру PvP
            from django.conf import settings
            active_tournament = Tournament.objects.filter(status='active').first()
            expires_at = timezone.now() + timedelta(days=settings.GAME_SETTINGS.get('ORDER_EXPIRY', 3))

            game = Game.objects.create(
                player1=user,
                player2=opponent_queue.user,
                bet_amount=bet_amount,
                player1_bet=bet_amount,
                player2_bet=bet_amount,
                game_bank=bet_amount * 2,
                tournament=active_tournament,
                game_type='pvp',
                status='betting',
                expires_at=expires_at,
            )

            # Очищаем очереди
            GameQueue.objects.filter(user__in=[user, opponent_queue.user]).delete()

            return JsonResponse({
                'success': True,
                'game_id': game.id,
                'opponent_found': True,
                'is_bot_game': False,
            })
    
    # Получаем пул ботов
    bot_pool = BotPool.get_pool()
    bot_balance = bot_pool.get_bot_balance()
    
    if bot_balance < bet_amount:
        return JsonResponse({'error': 'Бот временно недоступен'}, status=400)
    
    # Удаляем из очереди
    GameQueue.objects.filter(user=user).delete()
    
    # Создаем игру с ботом
    active_tournament = Tournament.objects.filter(status='active').first()
    
    with transaction.atomic():
        # Списываем ставку пользователя (деньги временно "заморожены" в банке игры)
        user.cf_balance -= bet_amount
        user.save(update_fields=['cf_balance'])
        
        # Используем баланс из пула ботов (ставка бота)
        bot_pool.use_balance(bet_amount)
        
        # Создаем игру с банком = сумма обеих ставок
        # Если игрок выиграет - получит весь банк (своя ставка + ставка бота)
        # Если игрок проиграет - потеряет свою ставку, ставка бота вернется в пул
        from django.conf import settings
        expires_at = timezone.now() + timedelta(days=settings.GAME_SETTINGS.get('ORDER_EXPIRY', 3))
        
        game = Game.objects.create(
            player1=user,
            player2=None,
            is_bot_game=True,
            bot_name=generate_bot_name(),  # Генерируем случайное имя для бота
            bot_balance=bot_balance,
            bet_amount=bet_amount,
            player1_bet=bet_amount,
            player2_bet=bet_amount,
            game_bank=bet_amount * 2,  # Банк = ставка игрока + ставка бота
            tournament=active_tournament,
            game_type='pve',
            status='betting',
            expires_at=expires_at,
            move_timer_start=timezone.now(),  # старт таймера сразу
        )
    
    # Ход бота будет определен после хода пользователя
    # Сохраняем только флаг, что это игра с ботом
    
    return JsonResponse({
        'success': True,
        'game_id': game.id,
        'bot_connected': True,
    })


@csrf_exempt
def api_leaderboard(request):
    """API для получения таблицы лидеров"""
    active_tournament = Tournament.objects.filter(status='active').first()
    
    if not active_tournament:
        return JsonResponse({
            'tournament_active': False,
            'leaderboard': [],
        })
    
    top_10 = active_tournament.get_top_10()
    leaderboard = []
    
    for participant in top_10:
        leaderboard.append({
            'user_id': participant.user.telegram_id,
            'username': mask_last(str(participant.user)),
            'points': participant.points,
            'games_played': participant.games_played,
            'wins': participant.wins,
            'draws': participant.draws,
            'losses': participant.losses,
        })
    
    # Проверяем место текущего пользователя
    user_rank = None
    if request.user:
        user_rank = active_tournament.get_participant_rank(request.user)
        if user_rank:
            user_participant = TournamentParticipant.objects.filter(
                tournament=active_tournament,
                user=request.user
            ).first()
            if user_participant:
                leaderboard.append({
                    'user_id': request.user.telegram_id,
                    'username': mask_last(str(request.user)),
                    'points': user_participant.points,
                    'games_played': user_participant.games_played,
                    'wins': user_participant.wins,
                    'draws': user_participant.draws,
                    'losses': user_participant.losses,
                    'rank': user_rank,
                    'is_current_user': True,
                })
    
    return JsonResponse({
        'tournament_active': True,
        'leaderboard': leaderboard,
        'user_rank': user_rank,
    })


@csrf_exempt
def api_recent_games(request):
    user = request.user

    recent_games = Game.objects.filter(
        Q(player1=user) | Q(player2=user),
        status='finished'
    ).order_by('-finished_at')[:5]

    games_list = []
    for game in recent_games:
        is_player1 = (game.player1 == user)
        opponent = game.player2 if is_player1 else game.player1

        if game.result == 'draw':
            result = 'draw'
            amount = 0
        elif (game.result == 'player1_win' and is_player1) or (game.result == 'player2_win' and not is_player1):
            result = 'win'
            amount = float(game.game_bank)
        else:
            result = 'loss'
            amount = float(game.player1_bet if is_player1 else game.player2_bet)

        # ✅ скрываем и игрока, и бота (бот НЕ должен называться "Бот")
        if game.is_bot_game:
            bot_display = mask_last(game.bot_name or generate_bot_name())
            opponent_display = bot_display
        else:
            opponent_display = mask_last(str(opponent)) if opponent else "unknown"

        games_list.append({
            'id': game.id,
            'opponent': opponent_display,  # ✅ МАСКА
            'bet_amount': float(game.bet_amount),
            'amount': amount,
            'result': result,
            'date': game.finished_at.strftime('%d.%m %H:%M') if game.finished_at else '',
        })

    return JsonResponse({'games': games_list})


@csrf_exempt
def api_top_players(request):
    """API для получения топ-5 игроков"""
    top_5_players = get_top_5_players()
    
    players_list = []
    for player in top_5_players:
        players_list.append({
            'rank': player['rank'],
            'user_id': player['user'].telegram_id,
            'username': mask_last(str(player['user'])),
            'wins': player['wins'],
            'losses': player['losses'],
            'draws': player['draws'],
            'total_games': player['total_games'],
            'win_rate': round(player['win_rate'], 1),  # Округляем до 1 знака
        })
    
    return JsonResponse({
        'players': players_list,
    })


@csrf_exempt
def api_rematch(request):
    """API для создания новой игры с тем же соперником"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    user = request.user
    
    try:
        data = json.loads(request.body)
        game_id = data.get('game_id')
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid request'}, status=400)
    
    if not game_id:
        return JsonResponse({'error': 'Game ID required'}, status=400)
    
    # Получаем завершенную игру
    try:
        old_game = Game.objects.get(id=game_id)
    except Game.DoesNotExist:
        return JsonResponse({'error': 'Game not found'}, status=404)
    
    # Проверяем, что пользователь участвовал в игре
    if old_game.player1 != user and (not old_game.player2 or old_game.player2 != user):
        return JsonResponse({'error': 'Not your game'}, status=403)
    
    # Проверяем, что игра завершена или отменена
    if old_game.status not in ['finished', 'cancelled']:
        return JsonResponse({'error': 'Game is not finished'}, status=400)
    
    # Определяем соперника и ставку
    if old_game.is_bot_game:
        # Для игры с ботом - создаем новую игру с ботом
        bet_amount = old_game.bet_amount
        
        # Проверяем баланс
        user.refresh_from_db()
        if user.cf_balance < bet_amount:
            return JsonResponse({'error': 'Недостаточно средств'}, status=400)
        
        # Получаем пул ботов
        bot_pool = BotPool.get_pool()
        bot_balance = bot_pool.get_bot_balance()
        
        if bot_balance < bet_amount:
            return JsonResponse({'error': 'Бот временно недоступен'}, status=400)
        
        # Создаем новую игру с ботом
        active_tournament = Tournament.objects.filter(status='active').first()
        from django.conf import settings
        expires_at = timezone.now() + timedelta(days=settings.GAME_SETTINGS.get('ORDER_EXPIRY', 3))
        
        with transaction.atomic():
            # Списываем ставку пользователя
            user.cf_balance -= bet_amount
            user.save(update_fields=['cf_balance'])
            
            # Используем баланс из пула ботов
            bot_pool.use_balance(bet_amount)
            
            # Создаем игру с тем же именем бота
            new_game = Game.objects.create(
                player1=user,
                player2=None,
                is_bot_game=True,
                bot_name=old_game.bot_name or generate_bot_name(),  # Используем то же имя бота
                bot_balance=bot_balance,
                bet_amount=bet_amount,
                player1_bet=bet_amount,
                player2_bet=bet_amount,
                game_bank=bet_amount * 2,
                tournament=active_tournament,
                game_type='pve',
                status='betting',
                expires_at=expires_at,
                move_timer_start=timezone.now(),
            )
        
        return JsonResponse({
            'success': True,
            'game_id': new_game.id,
            'is_bot_game': True,
        })
    else:
        # Для PvP игры - создаем новую игру с тем же соперником
        opponent = old_game.player2 if old_game.player1 == user else old_game.player1
        bet_amount = old_game.bet_amount
        
        # Проверяем балансы
        user.refresh_from_db()
        opponent.refresh_from_db()
        
        if user.cf_balance < bet_amount:
            return JsonResponse({'error': 'Недостаточно средств'}, status=400)
        
        if opponent.cf_balance < bet_amount:
            return JsonResponse({'error': 'У соперника недостаточно средств'}, status=400)
        
        # Проверяем, не находится ли соперник уже в активной игре
        opponent_active_game = Game.objects.filter(
            (Q(player1=opponent) | Q(player2=opponent)),
            status__in=['waiting', 'betting', 'playing']
        ).first()
        
        if opponent_active_game:
            return JsonResponse({'error': 'Соперник уже в игре'}, status=400)
        
        # Создаем новую игру
        active_tournament = Tournament.objects.filter(status='active').first()
        from django.conf import settings
        expires_at = timezone.now() + timedelta(days=settings.GAME_SETTINGS.get('ORDER_EXPIRY', 3))
        
        with transaction.atomic():
            # Списываем ставки
            user.cf_balance -= bet_amount
            opponent.cf_balance -= bet_amount
            user.save(update_fields=['cf_balance'])
            opponent.save(update_fields=['cf_balance'])
            
            # Создаем игру
            new_game = Game.objects.create(
                player1=user,
                player2=opponent,
                bet_amount=bet_amount,
                player1_bet=bet_amount,
                player2_bet=bet_amount,
                game_bank=bet_amount * 2,
                tournament=active_tournament,
                game_type='pvp',
                status='betting',
                expires_at=expires_at,
                move_timer_start=timezone.now(),
            )
        
        return JsonResponse({
            'success': True,
            'game_id': new_game.id,
            'is_bot_game': False,
        })

