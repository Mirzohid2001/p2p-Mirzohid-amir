"""
Уведомление «вас скинули в турнирной таблице».

Когда игрок набирает очки и обгоняет других участников турнира, каждому
обогнанному приходит сообщение в Telegram с новым местом и кнопкой «Играть».
Одному участнику — не чаще раза в COOLDOWN, чтобы не спамить.
"""
import logging
import threading
from datetime import timedelta
from urllib.parse import quote

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

COOLDOWN = timedelta(minutes=15)
SITE_URL = getattr(settings, "SITE_URL", "https://floracoin.cc")

TEXT = {
    "ru": ("Вас скинули в турнирной таблице 😝\nТеперь вы на {place}-м месте. Отыграйтесь!", "🎮 Играть"),
    "en": ("You've been knocked down the tournament table 😝\nYou're now in place #{place}. Win it back!", "🎮 Play"),
}

log = logging.getLogger(__name__)


def notify_overtaken(tournament, participants, points_before):
    """
    participants  — участники, которым только что начислили очки за игру;
    points_before — {participant.pk: очки до игры}.
    Ошибки здесь никогда не ломают саму игру.
    """
    from .models import TournamentParticipant

    try:
        now = timezone.now()
        not_recent = Q(overtaken_notified_at__isnull=True) | Q(overtaken_notified_at__lt=now - COOLDOWN)
        targets = {}
        for p in participants:
            old = points_before.get(p.pk, p.points)
            if p.points <= old:
                continue
            # были выше или наравне с игроком, а теперь ниже него (в том числе его соперник по этой игре)
            overtaken = (
                TournamentParticipant.objects
                .filter(tournament=tournament, points__gte=old, points__lt=p.points, points__gt=0)
                .exclude(pk=p.pk)
                .filter(not_recent)
                .select_related("user")
            )
            for x in overtaken:
                targets[x.pk] = x

        messages = []
        for x in targets.values():
            # помечаем атомарно: если параллельная игра уже отправила уведомление, второй раз не шлём
            if not TournamentParticipant.objects.filter(pk=x.pk).filter(not_recent).update(overtaken_notified_at=now):
                continue
            place = 1 + TournamentParticipant.objects.filter(tournament=tournament, points__gt=x.points).count()
            messages.append((x.user.telegram_id, (x.user.language or "ru").lower(), place))

        if messages:
            transaction.on_commit(
                lambda: threading.Thread(target=_send_all, args=(messages,), daemon=True).start()
            )
    except Exception:
        log.exception("Не удалось подготовить уведомления об обгоне в турнире")


def _play_url(telegram_id):
    from users.auth_token import make_token
    return f"{SITE_URL}/rps/?tg_id={quote(make_token(telegram_id))}"


def _send_all(messages):
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if not token or token == "YOUR_BOT_TOKEN":
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for telegram_id, lang, place in messages:
        text, button = TEXT.get(lang, TEXT["ru"])
        try:
            requests.post(url, json={
                "chat_id": telegram_id,
                "text": text.format(place=place),
                "reply_markup": {"inline_keyboard": [[{"text": button, "web_app": {"url": _play_url(telegram_id)}}]]},
            }, timeout=10)
        except Exception:
            log.warning("Не удалось отправить уведомление об обгоне пользователю %s", telegram_id)
