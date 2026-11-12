"""
Напоминание о поливе.

Запускается по расписанию каждые 10 минут (/etc/cron.d/flora-water-reminder).
Одно напоминание на каждый полив: полил → через WATER_DURATION часов вода кончилась →
пришло одно сообщение с кнопкой «Полить». Следующее — только после нового полива.

Пишем только активным игрокам (поливали за последние ACTIVE_WINDOW), чтобы не
будить тех, кто давно не играет. Если у игрока сохнут несколько деревьев —
одно сообщение на всех.

  manage.py notify_water_due            — отправить
  manage.py notify_water_due --dry-run  — только показать, кому ушло бы
"""
from collections import defaultdict
from datetime import timedelta
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q, F
from django.utils import timezone

from trees.models import Tree

ACTIVE_WINDOW = timedelta(hours=48)
SITE_URL = getattr(settings, "SITE_URL", "https://floracoin.cc")

TEXT = {
    "ru": ("💧 Пора поливать дерево! Вода закончилась — без полива оно не растёт.", "💧 Полить"),
    "en": ("💧 Time to water your tree! It ran out of water and stopped growing.", "💧 Water"),
}


def _play_url(telegram_id):
    from users.auth_token import make_token
    return f"{SITE_URL}/?tg_id={quote(make_token(telegram_id))}"


def send_reminder(telegram_id, lang):
    """Возвращает (статус, описание): "ok", "unreachable" (бот заблокирован / чат не найден) или "error"."""
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if not token or token == "YOUR_BOT_TOKEN":
        return "error", "no token"
    text, button = TEXT.get(lang, TEXT["ru"])
    try:
        resp = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={
            "chat_id": telegram_id,
            "text": text,
            "reply_markup": {"inline_keyboard": [[{"text": button, "web_app": {"url": _play_url(telegram_id)}}]]},
        }, timeout=10)
    except requests.RequestException as e:
        return "error", str(e)[:80]
    if resp.status_code == 200:
        return "ok", ""
    try:
        desc = resp.json().get("description", "")
    except ValueError:
        desc = resp.text[:80]
    # 403 — пользователь заблокировал бота, 400 — чат не найден / пользователь удалён: повторять бессмысленно
    if resp.status_code in (400, 403):
        return "unreachable", desc
    return "error", desc


class Command(BaseCommand):
    help = "Напоминает активным игрокам полить дерево, когда вода закончилась"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="ничего не отправлять, только показать")

    def handle(self, *args, dry_run=False, **options):
        now = timezone.now()
        dried_before = now - timedelta(hours=Tree.WATER_DURATION)

        qs = (
            Tree.objects.select_related("user")
            # вода кончилась, но поливали недавно — значит, игрок активный
            .filter(last_watered__lte=dried_before, last_watered__gte=now - ACTIVE_WINDOW)
            # автополив активен — не напоминаем
            .filter(Q(auto_water_until__isnull=True) | Q(auto_water_until__lte=now))
            # ещё не напоминали после последнего полива
            .filter(Q(water_reminder_sent_at__isnull=True) | Q(water_reminder_sent_at__lt=F("last_watered")))
        )

        by_user = defaultdict(list)
        for tree in qs:
            if tree.user and tree.user.telegram_id and not tree.is_watered():
                by_user[tree.user].append(tree)

        sent = unreachable = failed = 0
        reasons = defaultdict(int)
        for user, trees in by_user.items():
            if dry_run:
                self.stdout.write(f"  {user.telegram_id} ({len(trees)} дер.)")
                continue
            status, desc = send_reminder(user.telegram_id, (user.language or "ru").lower())
            if status in ("ok", "unreachable"):
                # недоступным тоже помечаем — до следующего полива больше не пробуем
                Tree.objects.filter(pk__in=[t.pk for t in trees]).update(water_reminder_sent_at=now)
            if status == "ok":
                sent += 1
            elif status == "unreachable":
                unreachable += 1
                reasons[desc] += 1
            else:
                failed += 1
                reasons[desc] += 1

        if dry_run:
            self.stdout.write(f"{timezone.localtime(now):%d.%m %H:%M} Ушло бы: {len(by_user)}")
            return
        line = f"{timezone.localtime(now):%d.%m %H:%M} Отправлено: {sent}, недоступны: {unreachable}, ошибок: {failed}"
        if reasons:
            line += " | " + "; ".join(f"{d} ×{n}" for d, n in reasons.items())
        self.stdout.write(line)
