"""
Антибот для «камень-ножницы-бумага».

1) Детектор: после каждой партии с ботом смотрим на последние WINDOW партий игрока
   (после его последней пройденной проверки). Подозрительно, если
     • FAST_MOVES_LIMIT+ ходов быстрее FAST_MOVE_SECONDS (человек так не успевает);
     • интервалы между партиями слишком ровные (разброс меньше REGULAR_STDEV_SECONDS);
     • циклический ритм: время хода И пауза после результата повторяются (±PERIODIC_TOLERANCE)
       через один и тот же шаг (1–PERIODIC_MAX_LAG партий) в PERIODIC_SHARE+ партий окна —
       так играет скрипт с заранее заданными задержками по кругу.
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
PERIODIC_TOLERANCE = 0.06
PERIODIC_SHARE = 0.65
PERIODIC_MAX_LAG = 10
PERIODIC_MAX_PAUSE_SECONDS = 120   # окно с большим перерывом — это не непрерывная серия
MIN_SOLVE_SECONDS = 0.4
CHALLENGE_TTL_SECONDS = 600
OPTIONS_COUNT = 6
FRUITS = ["🍎", "🍌", "🍇", "🍓", "🍒", "🍍", "🥝", "🍉", "🍋", "🍑"]

log = logging.getLogger(__name__)


def get_guard(user):
    from .models import PlayerGuard
    guard, _ = PlayerGuard.objects.get_or_create(user=user)
    return guard


def _periodic_share(rows):
    """
    rows — партии по возрастанию времени (created_at, finished_at), WINDOW+1 шт.
    Возвращает (лучшая доля совпадений, шаг) или None.
    """
    if len(rows) < WINDOW + 1:
        return None
    react = [(f - c).total_seconds() for c, f in rows[1:]]
    pause = [(rows[i][0] - rows[i - 1][1]).total_seconds() for i in range(1, len(rows))]
    if max(pause) > PERIODIC_MAX_PAUSE_SECONDS:
        return None
    best = (0.0, 0)
    for k in range(1, PERIODIC_MAX_LAG + 1):
        n = len(react) - k
        if n < 15:
            break
        hits = sum(
            1 for i in range(k, len(react))
            if abs(react[i] - react[i - k]) <= PERIODIC_TOLERANCE and abs(pause[i] - pause[i - k]) <= PERIODIC_TOLERANCE
        )
        best = max(best, (hits / n, k))
    return best


def _detect(guard):
    """Причина подозрения или None."""
    from .models import Game

    qs = Game.objects.filter(
        player1_id=guard.user_id, is_bot_game=True, status="finished", finished_at__isnull=False
    )
    # окно — партии после прошлого подозрения (а не после прошлой проверки): иначе при частых
    # проверках (каждые 30/10 партий) окно из 30 партий никогда не набиралось бы
    if guard.last_strike_at:
        qs = qs.filter(created_at__gt=guard.last_strike_at)
    # на одну партию больше окна — чтобы посчитать паузу перед первой партией окна
    rows_ext = list(qs.order_by("-created_at").values_list("created_at", "finished_at")[:WINDOW + 1])
    rows = rows_ext[:WINDOW]
    if len(rows) < WINDOW:
        return None

    periodic = _periodic_share(list(reversed(rows_ext)))
    if periodic and periodic[0] >= PERIODIC_SHARE:
        return f"циклический ритм: {periodic[0] * 100:.0f}% партий повторяют задержки с шагом {periodic[1]}"

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




# ── Учащение проверок и блокировка ───────────────────────────────────────────
# Каждое подозрение детектора — «страйк». Страйки живут STRIKE_WINDOW: если сутки
# подозрений нет, счётчик обнуляется.
CHECK_EVERY_BY_STRIKES = {0: CHECK_EVERY, 1: 30, 2: 10}
BAN_STRIKES = 3                   # столько подозрений за сутки — блокировка
STRIKE_WINDOW_SECONDS = 24 * 3600
BAN_WRONG_IN_ROW = 5              # неверных ответов подряд — блокировка
BAN_IGNORED_ATTEMPTS = 30         # попыток начать игру при висящей проверке без ответа — блокировка
# Текст, который видит заблокированный игрок (причину видят только админы в админ-панели)
BAN_MESSAGE = "Вы заблокированы, за подозрительную активность"


def _active_strikes(guard):
    if guard.last_strike_at and (timezone.now() - guard.last_strike_at).total_seconds() <= STRIKE_WINDOW_SECONDS:
        return guard.strikes
    return 0


def check_every(guard):
    """Через сколько партий следующая плановая проверка (чем больше подозрений, тем чаще)."""
    return CHECK_EVERY_BY_STRIKES.get(_active_strikes(guard), min(CHECK_EVERY_BY_STRIKES.values()))


FIRST_BAN_HOURS = 3   # 1-я блокировка — 3 ч, 2-я — 6 ч, 3-я — 12 ч … (каждый раз ×2)


def ban_hours(ban_number):
    """Длительность блокировки №ban_number (1, 2, 3 …) в часах."""
    return FIRST_BAN_HOURS * 2 ** (max(1, ban_number) - 1)


def ban(guard, reason):
    from datetime import timedelta
    guard.ban_count += 1
    hours = ban_hours(guard.ban_count)
    guard.banned = True
    guard.ban_reason = reason[:200]
    guard.banned_at = timezone.now()
    guard.banned_until = guard.banned_at + timedelta(hours=hours)
    guard.check_required = False
    guard.challenge = None
    guard.save()
    log.warning("antibot: user %s banned from RPS for %sh (#%s): %s", guard.user_id, hours, guard.ban_count, reason)
    _disqualify_from_active_tournament(guard.user_id, reason)


def _disqualify_from_active_tournament(user_id, reason):
    """Заблокированный во время турнира выбывает из него до конца (вернуть — кнопкой в админке)."""
    from .models import Tournament, TournamentParticipant
    try:
        t = Tournament.objects.filter(status="active").order_by("-start_date").first()
        if not t:
            return
        p, _ = TournamentParticipant.objects.get_or_create(tournament=t, user_id=user_id)
        if not p.disqualified:
            p.disqualified = True
            p.disqualified_reason = f"блокировка антибота: {reason}"[:200]
            p.disqualified_at = timezone.now()
            p.save(update_fields=["disqualified", "disqualified_reason", "disqualified_at"])
    except Exception:
        log.exception("antibot: disqualify failed")


def _expire(guard):
    """Срок блокировки вышел: снова пускаем, но сначала — проверка с фруктом. Счётчик блокировок не сбрасывается."""
    guard.banned = False
    guard.strikes = 0
    guard.last_strike_at = timezone.now()   # детектор смотрит только новые партии
    guard.consecutive_failed = 0
    guard.blocked_attempts = 0
    guard.check_required = True
    guard.check_reason = "проверка после блокировки"
    guard.challenge = None
    guard.games_since_check = 0
    guard.save()


def is_banned(guard):
    """Блокировка действует сейчас? Истёкшую снимает сама."""
    if not guard or not guard.banned:
        return False
    if guard.banned_until and timezone.now() >= guard.banned_until:
        _expire(guard)
        return False
    return True


def unban(guard):
    """Снять блокировку и все подозрения (кнопка «Разблокировать» в админке — признаём ошибку)."""
    guard.banned = False
    guard.ban_reason = ""
    guard.banned_at = None
    guard.banned_until = None
    guard.ban_count = 0
    guard.strikes = 0
    guard.last_strike_at = timezone.now()  # старые партии больше не учитываются детектором
    guard.consecutive_failed = 0
    guard.blocked_attempts = 0
    guard.check_required = False
    guard.check_reason = ""
    guard.challenge = None
    guard.games_since_check = 0
    guard.suspicious_reason = ""
    guard.suspicious_at = None
    guard.save()


def ban_message(guard):
    return BAN_MESSAGE.format(reason=guard.ban_reason or "подозрительная активность")


def _banned_json(guard):
    return JsonResponse({"banned": True, "error": ban_message(guard)}, status=403)


def ban_reason_for(user):
    """Причина блокировки или пустая строка (для страниц игры)."""
    from .models import PlayerGuard
    guard = PlayerGuard.objects.filter(user=user, banned=True).first()
    return ban_message(guard) if is_banned(guard) else ""


def banned_response(user):
    """403, если игрок заблокирован в КНБ; иначе None."""
    from .models import PlayerGuard
    guard = PlayerGuard.objects.filter(user=user, banned=True).first()
    return _banned_json(guard) if is_banned(guard) else None


def record_game(game):
    """Вызывается после завершения партии. Ошибки здесь никогда не ломают игру."""
    try:
        if not game.is_bot_game or not game.player1_id or not game.finished_at:
            return
        guard = get_guard(game.player1)
        if is_banned(guard):
            return
        guard.games_since_check += 1
        if (game.finished_at - game.created_at).total_seconds() < FAST_MOVE_SECONDS:
            guard.fast_moves += 1

        reason = None
        every = check_every(guard)
        if guard.games_since_check >= every:
            reason = f"плановая проверка: {guard.games_since_check} партий"

        suspicious = _detect(guard)
        if suspicious and not guard.check_required:
            # новое подозрение — новый страйк
            strikes = _active_strikes(guard) + 1
            guard.strikes = strikes
            guard.last_strike_at = game.finished_at  # следующее окно детектора — партии после этой
            guard.suspicious_reason = suspicious
            guard.suspicious_at = timezone.now()
            if strikes >= BAN_STRIKES:
                ban(guard, f"{strikes} подозрения детектора за сутки — {suspicious}")
                return
            reason = suspicious

        if reason and not guard.check_required:
            guard.check_required = True
            guard.check_reason = reason
            guard.challenge = None
            guard.blocked_attempts = 0
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
    """403, если игрок заблокирован или должен пройти проверку; иначе None."""
    from .models import PlayerGuard

    guard = PlayerGuard.objects.filter(user=user).first()
    if not guard:
        return None
    if is_banned(guard):
        return _banned_json(guard)
    if not guard.check_required:
        return None

    # человек не может нажимать «играть» под окном с фруктами — так ломится только скрипт
    guard.blocked_attempts += 1
    if guard.blocked_attempts >= BAN_IGNORED_ATTEMPTS:
        ban(guard, f"{guard.blocked_attempts} попыток начать игру без ответа на проверку")
        return _banned_json(guard)
    guard.save(update_fields=["blocked_attempts", "updated_at"])
    return JsonResponse(
        {"error": "Подтвердите, что вы не бот", "human_check": _public(_current_challenge(guard))},
        status=403,
    )


def verify(user, challenge_id, choice):
    """Проверяет ответ. Возвращает словарь для JsonResponse."""
    guard = get_guard(user)
    if is_banned(guard):
        return {"passed": False, "banned": True, "error": ban_message(guard)}
    if not guard.check_required:
        return {"passed": True}

    guard.blocked_attempts = 0  # игрок отвечает — значит, видит окно
    ch = guard.challenge
    if not ch or ch.get("id") != challenge_id or time.time() - ch.get("issued", 0) > CHALLENGE_TTL_SECONDS:
        guard.save(update_fields=["blocked_attempts", "updated_at"])
        return {"passed": False, "error": "Задание устарело, попробуйте ещё раз",
                "human_check": _public(_new_challenge(guard))}

    too_fast = time.time() - ch.get("issued", 0) < MIN_SOLVE_SECONDS
    if choice == ch.get("target") and not too_fast:
        guard.check_required = False
        guard.check_reason = ""
        guard.challenge = None
        guard.games_since_check = 0
        guard.checks_passed += 1
        guard.consecutive_failed = 0
        guard.last_passed_at = timezone.now()
        guard.save()
        return {"passed": True}

    guard.checks_failed += 1
    guard.consecutive_failed += 1
    if guard.consecutive_failed >= BAN_WRONG_IN_ROW:
        ban(guard, f"{guard.consecutive_failed} неверных ответов на проверку подряд")
        return {"passed": False, "banned": True, "error": ban_message(guard)}
    guard.save(update_fields=["checks_failed", "consecutive_failed", "blocked_attempts", "updated_at"])
    return {"passed": False, "error": "Неверно, попробуйте ещё раз",
            "human_check": _public(_new_challenge(guard))}
