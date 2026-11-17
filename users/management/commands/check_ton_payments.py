"""
Автозачисление пополнений TON.

Раз в минуту смотрит входящие переводы на кошелёк проекта (через tonapi.io) и
зачисляет сумму на TON-баланс игрока, у которого в профиле привязан кошелёк-отправитель.
Каждая транзакция обрабатывается ровно один раз (TonProcessedTx).

Запускается постоянным сервисом: systemctl status flora-ton-payments
  manage.py check_ton_payments                 — работать постоянно
  manage.py check_ton_payments --once          — один проход и выйти
  manage.py check_ton_payments --once --dry-run — показать, что было бы зачислено, ничего не меняя
"""
import time
from decimal import Decimal

import requests
from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction
from django.db.models import F

from users.models import TonProcessedTx, User

TON_ADDRESS_FRIENDLY = "UQAaSqEaBNAXz4gz7oJvrYXLaKXGaoUcxXFKR4rdW8KPwzLp"
TONAPI_TOKEN = 'AFTVO4WU53DURMIAAAAPFEGJ4KJR4WP5NK55EHL4NZHSKFQ52TBCLCFBDKNK3IMP4ACVIWI'
TONAPI = "https://tonapi.io/v2"
POLL_SECONDS = 60
PAGE_LIMIT = 100
NANO = Decimal("1e9")


def _addr(obj):
    return obj.get("address") if isinstance(obj, dict) else obj


class Command(BaseCommand):
    help = "Автоматическое зачисление пополнений TON по привязанным кошелькам"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="один проход и выйти")
        parser.add_argument("--dry-run", action="store_true", help="ничего не зачислять, только показать")

    def handle(self, *args, once=False, dry_run=False, **kwargs):
        self.headers = {"Authorization": f"Bearer {TONAPI_TOKEN}"}
        self.dry_run = dry_run
        self.own = None
        while True:
            try:
                if not self.own:
                    # raw-адрес кошелька проекта (0:…) — раньше считался через tonsdk, теперь спрашиваем tonapi
                    r = requests.get(f"{TONAPI}/address/{TON_ADDRESS_FRIENDLY}/parse", headers=self.headers, timeout=20)
                    r.raise_for_status()
                    self.own = r.json()["raw_form"]
                self.poll()
            except Exception as e:
                self.stdout.write(f"[ERROR] {type(e).__name__}: {e}")
            if once:
                return
            time.sleep(POLL_SECONDS)

    def poll(self):
        r = requests.get(f"{TONAPI}/blockchain/accounts/{self.own}/transactions",
                         headers=self.headers, params={"limit": PAGE_LIMIT}, timeout=20)
        r.raise_for_status()
        txs = r.json().get("transactions", [])
        known = set(TonProcessedTx.objects.filter(tx_hash__in=[t["hash"] for t in txs]).values_list("tx_hash", flat=True))

        for tx in reversed(txs):  # от старых к новым
            tx_hash = tx["hash"]
            if tx_hash in known:
                continue
            in_msg = tx.get("in_msg") or {}
            sender = _addr(in_msg.get("source"))
            value = (Decimal(int(in_msg.get("value") or 0)) / NANO).quantize(Decimal("0.00000001"))

            # что не является пополнением от игрока — помечаем обработанным и не зачисляем
            skip = None
            if not sender:
                skip = "исходящая/внешняя транзакция"
            elif not tx.get("success", True) or (in_msg.get("bounced")):
                skip = "транзакция не прошла"
            elif value <= 0:
                skip = "нулевая сумма"
            elif sender == self.own:
                skip = "перевод кошелька проекта самому себе"
            if skip:
                self._mark(tx_hash, None, value, f"пропущено: {skip}")
                continue

            user = User.objects.filter(ton_wallet=sender).first()
            if not user:
                self._mark(tx_hash, None, value, f"нет игрока с кошельком {sender}")
                continue
            self._credit(tx_hash, user, value)

    def _mark(self, tx_hash, user, value, note):
        self.stdout.write(f"[SKIP] {tx_hash[:12]}… {value} TON — {note}")
        if self.dry_run:
            return
        try:
            TonProcessedTx.objects.create(tx_hash=tx_hash, user=user, value=value)
        except IntegrityError:
            pass

    def _credit(self, tx_hash, user, value):
        who = f"@{user.username}" if user.username else str(user.telegram_id)
        if self.dry_run:
            self.stdout.write(f"[DRY]  {tx_hash[:12]}… +{value} TON -> {who}")
            return
        try:
            with transaction.atomic():
                # запись о транзакции первой: уникальный hash не даст зачислить дважды
                TonProcessedTx.objects.create(tx_hash=tx_hash, user=user, value=value)
                User.objects.filter(pk=user.pk).update(ton_balance=F("ton_balance") + value)
            self.stdout.write(f"[OK]   {tx_hash[:12]}… +{value} TON -> {who}")
        except IntegrityError:
            pass  # уже зачислено параллельно
