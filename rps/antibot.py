"""
Антибот для «камень-ножницы-бумага».

1) Детектор: после каждой партии с ботом смотрим на последние WINDOW партий игрока
   (после его последней пройденной проверки). Подозрительно, если
     • FAST_MOVES_LIMIT+ ходов быстрее FAST_MOVE_SECONDS (человек так не успевает);
     • интервалы между партиями слишком ровные (разброс меньше REGULAR_STDEV_SECONDS).
2) Проверка «вы человек?»: нужна каждые CHECK_EVERY партий и сразу при подозрении.
   Пока не пройдена — новую партию начать нельзя (поиск, бот, «Ещё раз» отвечают 403).
   Задание: нажать на нужный фрукт среди перемешанных. Ответ быстрее MIN_SOLVE_SECONDS
   не засчитывается (так отвечает только скрипт).
"""
import logging
import random
import secrets
import statistics
import time

from django.http import JsonResponse
from django.utils import timezone

CHECK_EVERY = 100
WINDOW = 30
FAST_MOVE_SECONDS = 0.25
FAST_MOVES_LIMIT = 5
REGULAR_STDEV_SECONDS = 0.15
REGULAR_MAX_GAP_SECONDS = 60
MIN_SOLVE_SECONDS = 0.4
CHALLENGE_TTL_SECONDS = 600
OPTIONS_COUNT = 6
FRUITS = ["🍎", "🍌", "🍇", "🍓", "🍒", "🍍", "🥝", "🍉", "🍋", "🍑"]

log = logging.getLogger(__name__)


def get_guard(user):
    from .models import PlayerGuard
    guard, _ = PlayerGuard.objects.get_or_create(user=user)
    return guard


def _detect(guard):
    """Причина подозрения или None."""
    from .models import Game

    qs = Game.objects.filter(
        player1_id=guard.user_id, is_bot_game=True, status="finished", finished_at__isnull=False
    )
    if guard.last_passed_at:
        qs = qs.filter(created_at__gt=guard.last_passed_at)
    rows = list(qs.order_by("-created_at").values_list("created_at", "finished_at")[:WINDOW])
    if len(rows) < WINDOW:
        return None

    fast = sum(1 for c, f in rows if (f - c).total_seconds() < FAST_MOVE_SECONDS)
    if fast >= FAST_MOVES_LIMIT:
        return f"{fast} из {WINDOW} ходов быстрее {FAST_MOVE_SECONDS} с"

    starts = sorted(c for c, _ in rows)
    gaps = [(b - a).total_seconds() for a, b in zip(starts, starts[1:])]
    gaps = [g for g in gaps if g <= REGULAR_MAX_GAP_SECONDS]
    if len(gaps) >= WINDOW - 5:
        spread = statistics.pstdev(gaps)
        if spread < REGULAR_STDEV_SECONDS:
            return f"слишком ровный ритм партий (±{spread:.2f} с)"
    return None


def record_game(game):
    """Вызывается после завершения партии. Ошибки здесь никогда не ломают игру."""
    try:
        if not game.is_bot_game or not game.player1_id or not game.finished_at:
            return
        guard = get_guard(game.player1)
        guard.games_since_check += 1
        if (game.finished_at - game.created_at).total_seconds() < FAST_MOVE_SECONDS:
            guard.fast_moves += 1

        reason = None
        if guard.games_since_check >= CHECK_EVERY:
            reason = f"плановая проверка: {guard.games_since_check} партий"
        suspicious = _detect(guard)
        if suspicious:
            reason = suspicious
            if not guard.check_required or guard.suspicious_reason != suspicious:
                guard.suspicious_reason = suspicious
                guard.suspicious_at = timezone.now()

        if reason and not guard.check_required:
            guard.check_required = True
            guard.check_reason = reason
            guard.challenge = None
        guard.save()
    except Exception:
        log.exception("antibot.record_game failed")


def _new_challenge(guard):
    target = random.choice(FRUITS)
    options = random.sample([f for f in FRUITS if f != target], OPTIONS_COUNT - 1) + [target]
    random.shuffle(options)
    guard.challenge = {
        "id": secrets.token_urlsafe(8),
        "target": target,
        "options": options,
        "issued": time.time(),
    }
    guard.save(update_fields=["challenge", "updated_at"])
    return guard.challenge


def _public(ch):
    return {"id": ch["id"], "target": ch["target"], "options": ch["options"]}


def _current_challenge(guard):
    ch = guard.challenge
    if not ch or time.time() - ch.get("issued", 0) > CHALLENGE_TTL_SECONDS:
        ch = _new_challenge(guard)
    return ch


def check_required_response(user):
    """JsonResponse 403 с заданием, если игроку нужно пройти проверку; иначе None."""
    from .models import PlayerGuard

    guard = PlayerGuard.objects.filter(user=user, check_required=True).first()
    if not guard:
        return None
    return JsonResponse(
        {"error": "Подтвердите, что вы не бот", "human_check": _public(_current_challenge(guard))},
        status=403,
    )


def verify(user, challenge_id, choice):
    """Проверяет ответ. Возвращает словарь для JsonResponse."""
    guard = get_guard(user)
    if not guard.check_required:
        return {"passed": True}

    ch = guard.challenge
    if not ch or ch.get("id") != challenge_id or time.time() - ch.get("issued", 0) > CHALLENGE_TTL_SECONDS:
        return {"passed": False, "error": "Задание устарело, попробуйте ещё раз",
                "human_check": _public(_new_challenge(guard))}

    too_fast = time.time() - ch.get("issued", 0) < MIN_SOLVE_SECONDS
    if choice == ch.get("target") and not too_fast:
        guard.check_required = False
        guard.check_reason = ""
        guard.challenge = None
        guard.games_since_check = 0
        guard.checks_passed += 1
        guard.last_passed_at = timezone.now()
        guard.save()
        return {"passed": True}

    guard.checks_failed += 1
    guard.save(update_fields=["checks_failed", "updated_at"])
    return {"passed": False, "error": "Неверно, попробуйте ещё раз",
            "human_check": _public(_new_challenge(guard))}
