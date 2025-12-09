from django.core.management.base import BaseCommand
from django.conf import settings
import os
import sys
import subprocess
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Telegram botni ishga tushirish'

    def add_arguments(self, parser):
        parser.add_argument(
            '--background',
            action='store_true',
            help='Botni background rejimida ishga tushirish',
        )

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('Telegram bot ishga tushirilmoqda...')
        )

        # Bot token tekshirish
        bot_token = getattr(settings, 'TG_BOT_TOKEN', None)
        if not bot_token:
            self.stdout.write(
                self.style.ERROR('TG_BOT_TOKEN settings.py da topilmadi!')
            )
            return

        # Bot faylini topish
        bot_file = os.path.join(settings.BASE_DIR, 'run_bot.py')
        if not os.path.exists(bot_file):
            self.stdout.write(
                self.style.ERROR(f'Bot fayli topilmadi: {bot_file}')
            )
            return

        try:
            if options['background']:
                # Background rejimida ishga tushirish
                self.stdout.write('Bot background rejimida ishga tushirildi')
                subprocess.Popen([sys.executable, bot_file])
            else:
                # Foreground rejimida ishga tushirish
                self.stdout.write('Bot ishga tushdi. To\'xtatish uchun Ctrl+C bosing')
                subprocess.run([sys.executable, bot_file])

        except KeyboardInterrupt:
            self.stdout.write(
                self.style.WARNING('\nBot to\'xtatildi')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Bot ishga tushirishda xatolik: {e}')
            ) 