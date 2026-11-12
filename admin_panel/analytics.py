"""Сбор аналитики для админ-панели."""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum, Q, Max
from django.db.models.functions import TruncDate
from django.utils import timezone

from users.models import User, TonDepositRequest
from rps.models import Game, GameQueue, Tournament, TournamentParticipant, BotPool, BotAdmin
from referrals.models import Referral, ReferralBonus, TaskCompletion
from shop.models import Purchase
from trees.models import Tree, TonDistribution, BurnedToken
from staking.models import Staking
from .models import TokenSupply, TokenOperation

LIVE_GAME_STATUSES = ("waiting", "betting", "playing")
DAYS = 30
LIVE_WINDOW = timedelta(hours=1)


def _live_games(now):
    return Game.objects.filter(status__in=LIVE_GAME_STATUSES, created_at__gte=now - LIVE_WINDOW)


def _stuck_games(now):
    return Game.objects.filter(status__in=LIVE_GAME_STATUSES, created_at__lt=now - LIVE_WINDOW)


def _d(v):
    return v if v is not None else Decimal("0")


def _day_start(now):
    local = timezone.localtime(now)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def _series(qs, field, days, start):
    """Количество записей по дням за последние `days` дней (в часовом поясе проекта)."""
    tz = timezone.get_current_timezone()
    rows = (
        qs.filter(**{f"{field}__gte": start})
        .annotate(day=TruncDate(field, tzinfo=tz))
        .values("day")
        .annotate(c=Count("pk"))
    )
    by_day = {r["day"]: r["c"] for r in rows}
    return [by_day.get((start + timedelta(days=i)).date(), 0) for i in range(days)]


def _active_users(since):
    """Пользователи, которые что-то делали после `since`: играли, поливали, собирали урожай, выполняли задания."""
    ids = set(Game.objects.filter(created_at__gte=since).values_list("player1_id", flat=True))
    ids |= set(Game.objects.filter(created_at__gte=since, player2__isnull=False).values_list("player2_id", flat=True))
    ids |= set(User.objects.filter(last_watered__gte=since).values_list("telegram_id", flat=True))
    ids |= set(Tree.objects.filter(Q(last_collected__gte=since) | Q(last_watered__gte=since)).values_list("user_id", flat=True))
    ids |= set(TaskCompletion.objects.filter(completed_at__gte=since).values_list("user_id", flat=True))
    ids |= set(Purchase.objects.filter(created_at__gte=since).values_list("user_id", flat=True))
    ids.discard(None)
    return ids


def _ever_active():
    """Пользователи, которые хоть раз что-то делали в игре (а не только нажали /start)."""
    ids = set(Game.objects.values_list("player1_id", flat=True))
    ids |= set(Game.objects.filter(player2__isnull=False).values_list("player2_id", flat=True))
    ids |= set(User.objects.filter(last_watered__isnull=False).values_list("telegram_id", flat=True))
    ids |= set(
        Tree.objects.filter(Q(last_collected__isnull=False) | Q(last_watered__isnull=False)).values_list("user_id", flat=True)
    )
    ids |= set(TaskCompletion.objects.values_list("user_id", flat=True))
    ids |= set(Purchase.objects.values_list("user_id", flat=True))
    ids.discard(None)
    return ids


def _activation(new_ids, active_ids):
    n = len(new_ids)
    a = len(new_ids & active_ids)
    return {"n": n, "active": a, "pct": round(100 * a / n) if n else 0}


def _dau_series(days, start):
    tz = timezone.get_current_timezone()
    per_day = {}

    def add(qs, date_field, user_field):
        for day, uid in (
            qs.filter(**{f"{date_field}__gte": start})
            .annotate(day=TruncDate(date_field, tzinfo=tz))
            .values_list("day", user_field)
        ):
            if uid is not None:
                per_day.setdefault(day, set()).add(uid)

    add(Game.objects.all(), "created_at", "player1_id")
    add(Game.objects.filter(player2__isnull=False), "created_at", "player2_id")
    add(Tree.objects.all(), "last_collected", "user_id")
    add(TaskCompletion.objects.all(), "completed_at", "user_id")
    add(Purchase.objects.all(), "created_at", "user_id")
    return [len(per_day.get((start + timedelta(days=i)).date(), ())) for i in range(days)]


def overview():
    now = timezone.now()
    today = _day_start(now)
    start = today - timedelta(days=DAYS - 1)
    users = User.objects.all()

    active_tournament = Tournament.objects.filter(status="active").order_by("-start_date").first()
    live_games = (
        _live_games(now)
        .select_related("player1", "player2")
        .order_by("-created_at")[:50]
    )

    ever = _ever_active()

    def new_ids(since=None):
        qs = users.filter(date_joined__gte=since) if since else users
        return set(qs.values_list("telegram_id", flat=True))

    activation = {
        "today": _activation(new_ids(today), ever),
        "d7": _activation(new_ids(today - timedelta(days=6)), ever),
        "d30": _activation(new_ids(start), ever),
        "all": _activation(new_ids(), ever),
    }

    return {
        "activation": activation,
        "activation_rows": [
            ("Сегодня", activation["today"]),
            ("За 7 дней", activation["d7"]),
            ("За 30 дней", activation["d30"]),
            ("За всё время", activation["all"]),
        ],
        "now": timezone.localtime(now),
        "labels": [(start + timedelta(days=i)).strftime("%d.%m") for i in range(DAYS)],
        "kpi": {
            "users_total": users.count(),
            "users_today": users.filter(date_joined__gte=today).count(),
            "users_7d": users.filter(date_joined__gte=today - timedelta(days=6)).count(),
            "users_30d": users.filter(date_joined__gte=start).count(),
            "active_15m": len(_active_users(now - timedelta(minutes=15))),
            "active_today": len(_active_users(today)),
            "active_7d": len(_active_users(today - timedelta(days=6))),
            "games_today": Game.objects.filter(created_at__gte=today).count(),
            "games_live": _live_games(now).count(),
            "games_stuck": _stuck_games(now).count(),
            "queue": GameQueue.objects.filter(expires_at__gt=now).count(),
            "refs_today": Referral.objects.filter(date_joined__gte=today).count(),
            "purchases_today": Purchase.objects.filter(created_at__gte=today).count(),
        },
        "series": {
            "registrations": _series(users, "date_joined", DAYS, start),
            "dau": _dau_series(DAYS, start),
            "games": _series(Game.objects.all(), "created_at", DAYS, start),
            "referrals": _series(Referral.objects.all(), "date_joined", DAYS, start),
        },
        "active_tournament": active_tournament,
        "live_games": live_games,
        "recent_users": users.select_related("referred_by").order_by("-date_joined")[:15],
    }


def games():
    now = timezone.now()
    today = _day_start(now)
    finished = Game.objects.filter(status="finished")
    pve = finished.filter(is_bot_game=True)
    pve_total = pve.count()
    pve_player_wins = pve.filter(result="player1_win").count()
    pve_draws = pve.filter(result="draw").count()

    active_tournament = Tournament.objects.filter(status="active").order_by("-start_date").first()
    top = []
    if active_tournament:
        top = (
            TournamentParticipant.objects.filter(tournament=active_tournament)
            .select_related("user")
            .order_by("-points", "-wins")[:20]
        )

    tournaments = (
        Tournament.objects.annotate(
            n_players=Count("participants", distinct=True),
            rewards=Sum("participants__reward_amount"),
        ).order_by("-start_date")[:10]
    )

    played = list(
        finished.values("player1_id").annotate(n=Count("id")).order_by("-n")[:15]
    )
    wins = dict(
        finished.filter(winner_id__in=[p["player1_id"] for p in played])
        .values("winner_id").annotate(w=Count("id")).values_list("winner_id", "w")
    )
    users_by_id = User.objects.in_bulk([p["player1_id"] for p in played])
    top_players = []
    for p in played:
        u = users_by_id.get(p["player1_id"])
        if u:
            u.n, u.w = p["n"], wins.get(u.pk, 0)
            top_players.append(u)

    agg = finished.aggregate(volume=Sum("bet_amount"), bank=Sum("game_bank"))
    pool = BotPool.objects.first()

    return {
        "games_total": Game.objects.count(),
        "games_finished": finished.count(),
        "games_today": Game.objects.filter(created_at__gte=today).count(),
        "games_cancelled": Game.objects.filter(status="cancelled").count(),
        "pvp": finished.filter(is_bot_game=False).count(),
        "pve": pve_total,
        "pve_player_wins": pve_player_wins,
        "pve_draws": pve_draws,
        "pve_bot_wins": pve_total - pve_player_wins - pve_draws,
        "pve_winrate": round(100 * pve_player_wins / pve_total, 1) if pve_total else 0,
        "volume": _d(agg["volume"]),
        "bank": _d(agg["bank"]),
        "bot_pool": pool,
        "live_games": _live_games(now).select_related("player1", "player2").order_by("-created_at")[:50],
        "stuck_games": _stuck_games(now).select_related("player1", "player2").order_by("-created_at")[:50],
        "queue": GameQueue.objects.filter(expires_at__gt=now).select_related("user").order_by("-created_at")[:50],
        "active_tournament": active_tournament,
        "tournament_top": top,
        "tournaments": tournaments,
        "top_players": top_players,
        "recent_games": Game.objects.filter(status="finished").select_related("player1", "player2", "winner").order_by("-finished_at", "-created_at")[:30],
    }


def economy():
    bal = User.objects.aggregate(
        cf=Sum("cf_balance"), ton=Sum("ton_balance"), branches=Sum("branches_balance"), staked=Sum("staking_cf")
    )
    trees_by = list(Tree.objects.values("type", "level").annotate(c=Count("id")).order_by("type", "level"))
    shop = list(
        Purchase.objects.values("item__name", "item__type", "item__price_token_type")
        .annotate(c=Count("id"), total=Sum("price_paid"))
        .order_by("-c")
    )
    tasks = list(TaskCompletion.objects.values("task__title", "task__reward_fl").annotate(c=Count("id")).order_by("-c"))
    bonuses = list(ReferralBonus.objects.values("bonus_type").annotate(c=Count("id"), total=Sum("amount")).order_by("bonus_type"))
    bonus_names = dict(ReferralBonus.BONUS_TYPE_CHOICES)
    for b in bonuses:
        b["name"] = bonus_names.get(b["bonus_type"], b["bonus_type"])
    deposits = TonDepositRequest.objects.aggregate(
        n=Count("id"), done=Count("id", filter=Q(is_completed=True)), total=Sum("amount", filter=Q(is_completed=True))
    )
    return {
        "cf_total_supply": TokenSupply.get_current_supply(),
        "cf_balance": _d(bal["cf"]),
        "ton_balance": _d(bal["ton"]),
        "branches": bal["branches"] or 0,
        "staked": _d(bal["staked"]),
        "burned": _d(BurnedToken.objects.aggregate(s=Sum("amount"))["s"]),
        "staking_active": Staking.objects.filter(status="active").count(),
        "trees_total": Tree.objects.count(),
        "trees_by": trees_by,
        "shop": shop,
        "tasks": tasks,
        "bonuses": bonuses,
        "deposits": deposits,
        "richest_cf": User.objects.order_by("-cf_balance")[:15],
        "richest_ton": User.objects.filter(ton_balance__gt=0).order_by("-ton_balance")[:15],
        "active_ton_distributions": TonDistribution.objects.filter(is_active=True).order_by("-created_at"),
        "past_ton_distributions": TonDistribution.objects.filter(is_active=False).order_by("-created_at")[:5],
        "recent_operations": TokenOperation.objects.order_by("-timestamp")[:15],
    }


def referrals():
    now = timezone.now()
    today = _day_start(now)
    top = (
        User.objects.annotate(
            n=Count("invited_users", distinct=True),
            n7=Count("invited_users", filter=Q(invited_users__date_joined__gte=today - timedelta(days=6)), distinct=True),
            last=Max("invited_users__date_joined"),
        )
        .filter(n__gt=0)
        .order_by("-n")[:30]
    )
    total = Referral.objects.count()
    users_total = User.objects.count()
    return {
        "total": total,
        "today": Referral.objects.filter(date_joined__gte=today).count(),
        "week": Referral.objects.filter(date_joined__gte=today - timedelta(days=6)).count(),
        "inviters": User.objects.filter(invited_users__isnull=False).distinct().count(),
        "share": round(100 * total / users_total, 1) if users_total else 0,
        "bonus_total": _d(ReferralBonus.objects.aggregate(s=Sum("amount"))["s"]),
        "top": top,
        "recent": Referral.objects.select_related("inviter", "invited").order_by("-date_joined")[:30],
    }


USER_SORTS = {
    "new": "-date_joined",
    "old": "date_joined",
    "cf": "-cf_balance",
    "ton": "-ton_balance",
    "refs": "-n_refs",
    "games": "-n_games",
}


def users_list(q="", sort="new"):
    qs = User.objects.select_related("referred_by").annotate(
        n_refs=Count("invited_users", distinct=True),
        n_games=Count("games_as_player1", distinct=True),
        n_trees=Count("trees", distinct=True),
    )
    q = (q or "").strip().lstrip("@")
    if q:
        cond = Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(ton_wallet__icontains=q)
        if q.isdigit():
            cond |= Q(telegram_id=int(q))
        qs = qs.filter(cond)
    return qs.order_by(USER_SORTS.get(sort, "-date_joined"))


def user_detail(telegram_id):
    user = User.objects.select_related("referred_by").get(telegram_id=telegram_id)
    games_qs = Game.objects.filter(Q(player1=user) | Q(player2=user))
    finished = games_qs.filter(status="finished")
    wins = finished.filter(winner=user).count()
    draws = finished.filter(result="draw").count()
    return {
        "u": user,
        "is_bot_admin": BotAdmin.objects.filter(telegram_id=user.telegram_id, is_active=True).exists(),
        "trees": Tree.objects.filter(user=user).order_by("type", "-level"),
        "games_total": games_qs.count(),
        "games_finished": finished.count(),
        "wins": wins,
        "draws": draws,
        "losses": finished.count() - wins - draws,
        "recent_games": games_qs.select_related("player1", "player2", "winner").order_by("-created_at")[:20],
        "invited": Referral.objects.filter(inviter=user).select_related("invited").order_by("-date_joined"),
        "ref_bonus": _d(ReferralBonus.objects.filter(referral__inviter=user).aggregate(s=Sum("amount"))["s"]),
        "purchases": Purchase.objects.filter(user=user).select_related("item").order_by("-created_at")[:20],
        "tasks": TaskCompletion.objects.filter(user=user).select_related("task").order_by("-completed_at"),
        "tournaments": TournamentParticipant.objects.filter(user=user).select_related("tournament").order_by("-created_at"),
    }
