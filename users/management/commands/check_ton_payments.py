import time
import requests
from decimal import Decimal
from django.core.management.base import BaseCommand
from tonsdk.utils import Address
from users.models import TonProcessedTx, User

TON_ADDRESS_FRIENDLY = "UQAW1dSI8WjwEXnAQ98MJVYyOQ8D7egvHmKxAvH_XWRLjr-r"
from tonsdk.utils import Address

def to_raw(addr: str) -> str:
    if not addr:
        return ""
    try:
        return Address(addr).to_string(is_user_friendly=False)
    except Exception:
        return str(addr)
TON_ADDRESS = Address(
    TON_ADDRESS_FRIENDLY
).to_string(is_user_friendly=False)
# TON_ADDRESS = '0:16d5d488f168f01179c043df0c255632390f03ede82f1e62b102f1ff5d644b8e'
TONAPI_TOKEN = 'AFTVO4WU53DURMIAAAAPFEGJ4KJR4WP5NK55EHL4NZHSKFQ52TBCLCFBDKNK3IMP4ACVIWI'
API_URL = f'https://tonapi.io/v2/blockchain/accounts/{TON_ADDRESS}/transactions'

class Command(BaseCommand):
    help = 'Автоматическое зачисление TON по кошелькам'

    def handle(self, *args, **kwargs):
        headers = {"Authorization": f"Bearer {TONAPI_TOKEN}"}
        params = {"limit": 50}

        while True:
            try:
                resp = requests.get(API_URL, headers=headers, params=params, timeout=20)
                print("[DEBUG] Ответ от TONAPI:", resp.text)
                txs = resp.json().get("transactions", [])
                for tx in txs:
                    tx_hash = tx['hash']
                    if TonProcessedTx.objects.filter(tx_hash=tx_hash).exists():
                        continue

                    in_msg = tx.get('in_msg')
                    if not in_msg:
                        continue

                    dest = in_msg.get('destination')
                    if isinstance(dest, dict):
                        dest_addr = dest.get('address')
                    else:
                        dest_addr = dest

                    # Сравниваем именно raw TON адрес (0:...)
                    if dest_addr != TON_ADDRESS:
                        continue

                    sender = in_msg.get('source')
                    if isinstance(sender, dict):
                        sender_addr = sender.get('address')
                    else:
                        sender_addr = sender

                    value = (Decimal(in_msg['value']) / Decimal('1e9')).quantize(Decimal('0.00000001'))

                    user = User.objects.filter(ton_wallet=sender_addr).first()
                    if user:
                        user.ton_balance += value
                        user.save()
                        print(f"[INFO] Пользователь {user.username or user.telegram_id} пополнил TON на {value}")
                        TonProcessedTx.objects.create(
                            tx_hash=tx_hash,
                            user=user,
                            value=value
                        )
                    else:
                        print(f"[WARN] Нет пользователя с TON кошельком {sender_addr}")
                        TonProcessedTx.objects.create(
                            tx_hash=tx_hash,
                            user=None,
                            value=value
                        )

                print("Ожидание 60 сек...")
                time.sleep(60)
            except Exception as e:
                print(f"[ERROR] {e}")
                time.sleep(60)