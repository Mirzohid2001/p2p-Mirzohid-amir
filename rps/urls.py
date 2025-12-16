from django.urls import path
from . import views

app_name = 'rps'

urlpatterns = [
    path('', views.rps_home, name='home'),
    path('game/', views.rps_game, name='game'),
    path('game/<int:game_id>/', views.rps_game, name='game_detail'),
    
    # API endpoints
    path('api/search/', views.api_search_game, name='api_search'),
    path('api/search/cancel/', views.api_cancel_search, name='api_cancel_search'),
    path('api/move/', views.api_make_move, name='api_move'),
    path('api/game/<int:game_id>/status/', views.api_game_status, name='api_game_status'),
    path('api/bot/connect/', views.api_connect_bot, name='api_connect_bot'),
    path('api/game/cancel/', views.api_cancel_game, name='api_cancel_game'),
    path('api/leaderboard/', views.api_leaderboard, name='api_leaderboard'),
    path('api/recent-games/', views.api_recent_games, name='api_recent_games'),
    path('api/top-players/', views.api_top_players, name='api_top_players'),
]

