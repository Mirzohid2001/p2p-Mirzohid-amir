from django.contrib import admin
from .models import Tournament, TournamentParticipant, Game, GameQueue, BotPool, BotAdmin


@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    list_display = ['id', 'status', 'start_date', 'end_date', 'reward_date']
    list_filter = ['status', 'start_date']
    search_fields = ['id']


@admin.register(TournamentParticipant)
class TournamentParticipantAdmin(admin.ModelAdmin):
    list_display = ['user', 'tournament', 'points', 'games_played', 'wins', 'draws', 'losses', 'reward_received']
    list_filter = ['tournament', 'reward_received']
    search_fields = ['user__username', 'user__first_name']


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ['id', 'game_type', 'status', 'player1', 'player2', 'bet_amount', 'winner', 'created_at']
    list_filter = ['game_type', 'status', 'created_at']
    search_fields = ['player1__username', 'player2__username']


@admin.register(GameQueue)
class GameQueueAdmin(admin.ModelAdmin):
    list_display = ['user', 'bet_amount', 'created_at', 'expires_at']
    list_filter = ['created_at']


@admin.register(BotPool)
class BotPoolAdmin(admin.ModelAdmin):
    list_display = ['total_balance', 'used_balance']


@admin.register(BotAdmin)
class BotAdminAdmin(admin.ModelAdmin):
    list_display = ['user', 'telegram_id', 'added_by', 'added_at', 'is_active']
    list_filter = ['is_active', 'added_at']
    search_fields = ['telegram_id', 'user__username', 'user__first_name']
    readonly_fields = ['added_at']

