from datetime import timedelta
import os
import requests

from django.core.management.base import BaseCommand
from django.db.models import Q, F
from django.utils import timezone

from trees.models import Tree


def send_telegram_message(chat_id: int, text: str) -> bool:
    token = os.getenv("BOT_TOKEN")  # положи токен в env на сервере
    if not token:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    return resp.status_code == 200


class Command(BaseCommand):
    help = "Send watering reminder when 5 hours passed after last watering"

    def handle(self, *args, **options):
        now = timezone.now()
        threshold = now - timedelta(hours=Tree.WATER_DURATION)

        # Деревья, которые НЕ политые (вода кончилась), и прошло >= 5 часов с last_watered
        qs = (
            Tree.objects.select_related("user")
            .filter(last_watered__isnull=False, last_watered__lte=threshold)
            .filter(
                # автополив активен? тогда не напоминаем
                Q(auto_water_until__isnull=True) | Q(auto_water_until__lte=now)
            )
            .filter(
                # ещё не напоминали после последнего полива
                Q(water_reminder_sent_at__isnull=True) | Q(water_reminder_sent_at__lt=F("last_watered"))
            )
        )

        sent = 0
        for tree in qs.iterator():
            tg_id = getattr(tree.user, "telegram_id", None)
            if not tg_id:
                continue

            # на всякий случай не шлём, если внезапно снова "is_watered"
            if tree.is_watered():
                continue

            text = "💧 Пора поливать дерево! Прошло 5 часов с последнего полива."
            ok = send_telegram_message(tg_id, text)
            if ok:
                tree.water_reminder_sent_at = now
                tree.save(update_fields=["water_reminder_sent_at"])
                sent += 1

        self.stdout.write(self.style.SUCCESS(f"Sent reminders: {sent}"))
