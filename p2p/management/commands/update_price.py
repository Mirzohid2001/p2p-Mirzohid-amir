from django.core.management.base import BaseCommand
from django.utils import timezone

from p2p.models import PriceHistory


class Command(BaseCommand):
    help = "Add daily price point"

    def handle(self, *args, **kwargs):
        today = timezone.localdate()
        last = PriceHistory.objects.order_by('-date').first()
        if last and last.date == today:
            self.stdout.write("Already updated today.")
            return
        new_price = last.price + 1 if last else 1
        PriceHistory.objects.create(date=today, price=new_price)
        self.stdout.write(f"New price for {today}: {new_price}")
