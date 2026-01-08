from django.db import models
from django.utils import timezone
from django.db.models import Sum, Count, Q
from decimal import Decimal
from users.models import User


class Tournament(models.Model):
    """Турнир по игре Камень-Ножницы-Бумага"""
    STATUS_CHOICES = [
        ('active', 'Активный'),
        ('completed', 'Завершен'),
        ('rewarded', 'Награды выданы'),
    ]
    
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    start_date = models.DateTimeField(auto_now_add=True)
    end_date = models.DateTimeField(null=True, blank=True)
    reward_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Турнир'
        verbose_name_plural = 'Турниры'
        ordering = ['-start_date']
    
    def __str__(self):
        return f"Турнир #{self.id} ({self.get_status_display()})"
    
    def is_active(self):
        """Проверяет, активен ли турнир"""
        if self.status != 'active':
            return False
        if self.end_date and timezone.now() > self.end_date:
            return False
        return True
    
    def get_top_10(self):
        """Возвращает топ-10 участников"""
        return self.participants.all().order_by('-points')[:10]
    
    def get_participant_rank(self, user):
        """Возвращает место пользователя в турнире"""
        participants = self.participants.all().order_by('-points')
        for idx, participant in enumerate(participants, 1):
            if participant.user == user:
                return idx
        return None


class TournamentParticipant(models.Model):
    """Участник турнира"""
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tournament_participations')
    points = models.IntegerField(default=0)
    games_played = models.IntegerField(default=0)
    wins = models.IntegerField(default=0)
    draws = models.IntegerField(default=0)
    losses = models.IntegerField(default=0)
    coins_won = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    coins_lost = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    reward_received = models.BooleanField(default=False)
    reward_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Участник турнира'
        verbose_name_plural = 'Участники турниров'
        unique_together = ['tournament', 'user']
        ordering = ['-points', 'games_played']
    
    def __str__(self):
        return f"{self.user} - {self.points} очков"
    
    def add_points(self, result):
        """Добавляет очки в зависимости от результата: win=3, draw=1, loss=0"""
        if result == 'win':
            self.points += 3
            self.wins += 1
        elif result == 'draw':
            self.points += 1
            self.draws += 1
        elif result == 'loss':
            self.losses += 1
        self.games_played += 1
        self.save()


class Game(models.Model):
    """Игровая сессия Камень-Ножницы-Бумага"""
    STATUS_CHOICES = [
        ('waiting', 'Ожидание игроков'),
        ('betting', 'Выбор ставки'),
        ('playing', 'Игра идет'),
        ('finished', 'Завершена'),
        ('cancelled', 'Отменена'),
    ]
    
    GAME_TYPE_CHOICES = [
        ('pvp', 'Игрок vs Игрок'),
        ('pve', 'Игрок vs Бот'),
    ]
    
    tournament = models.ForeignKey(Tournament, on_delete=models.SET_NULL, null=True, blank=True, related_name='games')
    game_type = models.CharField(max_length=3, choices=GAME_TYPE_CHOICES, default='pvp')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='waiting')
    
    # Игроки
    player1 = models.ForeignKey(User, on_delete=models.CASCADE, related_name='games_as_player1')
    player2 = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='games_as_player2')
    is_bot_game = models.BooleanField(default=False)
    bot_name = models.CharField(max_length=50, null=True, blank=True)  # Случайное имя для бота
    bot_balance = models.DecimalField(max_digits=15, decimal_places=2, default=1000)
    
    # Ставки
    bet_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    player1_bet = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    player2_bet = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    game_bank = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Ходы
    player1_move = models.CharField(max_length=10, null=True, blank=True)  # rock, paper, scissors
    player2_move = models.CharField(max_length=10, null=True, blank=True)
    
    # Результат
    winner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='won_games')
    result = models.CharField(max_length=10, null=True, blank=True)  # player1_win, player2_win, draw
    
    # Таймеры
    move_timer_start = models.DateTimeField(null=True, blank=True)
    search_timer_start = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)  # Для автоматического истечения ордеров
    
    class Meta:
        verbose_name = 'Игра'
        verbose_name_plural = 'Игры'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Игра #{self.id} - {self.player1} vs {self.player2 or 'Бот'}"
    
    def calculate_result(self):
        """
        Вычисляет результат игры по правилам:
        - Камень бьет ножницы
        - Ножницы бьют бумагу
        - Бумага бьет камень
        - Одинаковые ходы = ничья
        """
        if not self.player1_move or not self.player2_move:
            return None
        
        # Правила игры
        moves = {
            'rock': {'beats': 'scissors', 'loses_to': 'paper'},      # Камень бьет ножницы, проигрывает бумаге
            'paper': {'beats': 'rock', 'loses_to': 'scissors'},      # Бумага бьет камень, проигрывает ножницам
            'scissors': {'beats': 'paper', 'loses_to': 'rock'},    # Ножницы бьют бумагу, проигрывают камню
        }
        
        p1_move = moves.get(self.player1_move)
        p2_move = moves.get(self.player2_move)
        
        if not p1_move or not p2_move:
            return None
        
        # Ничья
        if self.player1_move == self.player2_move:
            return 'draw'
        # Игрок 1 выиграл
        elif p1_move['beats'] == self.player2_move:
            return 'player1_win'
        # Игрок 2 выиграл
        else:
            return 'player2_win'
    
    def finish_game(self):
        """
        Завершает игру и распределяет награды.
        
        Логика:
        - При создании игры ставки уже списаны с балансов обоих игроков
        - game_bank = player1_bet + player2_bet (общий банк)
        - При ничьей: возвращаем ставки обоим игрокам
        - При победе: победитель получает весь банк (game_bank)
          - Победитель получает: свои ставки + ставки проигравшего
          - Проигравший теряет свою ставку (уже списана при создании игры)
        """
        result = self.calculate_result()
        if not result:
            return
        
        self.result = result
        self.status = 'finished'
        self.finished_at = timezone.now()
        
        # Обновляем балансы
        if result == 'draw':
            # Ничья: возвращаем ставки обоим игрокам
            # (ставки уже были списаны при создании игры)
            self.player1.cf_balance += self.player1_bet
            self.player1.save(update_fields=['cf_balance'])
            if self.player2:
                self.player2.cf_balance += self.player2_bet
                self.player2.save(update_fields=['cf_balance'])
            elif self.is_bot_game:
                # Для бота возвращаем баланс в пул при ничьей
                from .models import BotPool
                bot_pool = BotPool.get_pool()
                bot_pool.return_balance(self.player2_bet)
        else:
            # Победитель получает весь банк (обе ставки)
            if self.is_bot_game:
                if result == 'player1_win':
                    # Игрок выиграл - получает весь банк (своя ставка + ставка бота)
                    self.winner = self.player1
                    self.player1.cf_balance += self.game_bank
                    self.player1.save(update_fields=['cf_balance'])
                    # Баланс бота уже был использован из пула при создании игры
                else:
                    # Бот выиграл - возвращаем весь банк в пул (ставка игрока + ставка бота)
                    from .models import BotPool
                    bot_pool = BotPool.get_pool()
                    bot_pool.return_balance(self.game_bank)
                    # Игрок проиграл, его ставка уже списана при создании игры
            else:
                # PvP: победитель получает весь банк
                winner = self.player1 if result == 'player1_win' else self.player2
                self.winner = winner
                # Победитель получает: свои ставки + ставки проигравшего
                winner.cf_balance += self.game_bank
                winner.save(update_fields=['cf_balance'])
                # Проигравший уже потерял свою ставку при создании игры
        
        # Обновляем статистику турнира
        if self.tournament and self.tournament.is_active():
            participant1, _ = TournamentParticipant.objects.get_or_create(
                tournament=self.tournament,
                user=self.player1
            )
            participant2 = None
            if self.player2:
                participant2, _ = TournamentParticipant.objects.get_or_create(
                    tournament=self.tournament,
                    user=self.player2
                )
            
            if result == 'player1_win':
                participant1.add_points('win')
                if participant2:
                    participant2.add_points('loss')
            elif result == 'player2_win':
                if participant2:
                    participant2.add_points('win')
                participant1.add_points('loss')
            else:  # draw
                participant1.add_points('draw')
                if participant2:
                    participant2.add_points('draw')
        
        self.save()
        return result


class GameQueue(models.Model):
    """Очередь поиска игры"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='game_queues')
    bet_amount = models.DecimalField(max_digits=15, decimal_places=2)
    tournament = models.ForeignKey(Tournament, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    
    class Meta:
        verbose_name = 'Очередь игры'
        verbose_name_plural = 'Очереди игр'
        ordering = ['created_at']
    
    def __str__(self):
        return f"{self.user} - {self.bet_amount} CF"
    
    def is_expired(self):
        """Проверяет, истекла ли очередь"""
        return timezone.now() > self.expires_at


class BotPool(models.Model):
    """Пул балансов для ботов"""
    total_balance = models.DecimalField(max_digits=15, decimal_places=2, default=10000)
    used_balance = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    class Meta:
        verbose_name = 'Пул ботов'
        verbose_name_plural = 'Пулы ботов'
    
    @classmethod
    def get_pool(cls):
        """Получает или создает пул"""
        pool, _ = cls.objects.get_or_create(id=1)
        return pool
    
    def get_bot_balance(self):
        """Получает баланс для бота"""
        return min(1000, self.total_balance - self.used_balance)
    
    def use_balance(self, amount):
        """Использует баланс из пула"""
        self.used_balance += amount
        self.save()
    
    def return_balance(self, amount):
        """Возвращает баланс в пул"""
        self.used_balance = max(0, self.used_balance - amount)
        self.save()


class BotAdmin(models.Model):
    """Модель для хранения администраторов бота"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bot_admin')
    telegram_id = models.BigIntegerField(unique=True)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='added_admins')
    added_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = 'Администратор бота'
        verbose_name_plural = 'Администраторы бота'
        ordering = ['-added_at']
    
    def __str__(self):
        return f"Admin: {self.user} (ID: {self.telegram_id})"
    
    @classmethod
    def is_admin(cls, telegram_id):
        """Проверяет, является ли пользователь администратором"""
        return cls.objects.filter(telegram_id=telegram_id, is_active=True).exists()
    
    @classmethod
    def get_all_admins(cls):
        """Возвращает список всех активных администраторов"""
        return cls.objects.filter(is_active=True).select_related('user')

