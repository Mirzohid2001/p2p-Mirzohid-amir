from django.core.management.base import BaseCommand
from farm.models import User
import random
import string


class Command(BaseCommand):
    help = 'Генерирует реферальные коды для пользователей, у которых их нет'

    def handle(self, *args, **options):
        users_without_code = User.objects.filter(referral_code__isnull=True) | User.objects.filter(referral_code='')
        count = users_without_code.count()
        self.stdout.write(f"Найдено {count} пользователей без реферального кода")

        code_length = 8
        success_count = 0

        for user in users_without_code:
            # Генерируем уникальный реферальный код
            while True:
                code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=code_length))
                if not User.objects.filter(referral_code=code).exists():
                    break

            user.referral_code = code
            user.save(update_fields=['referral_code'])
            success_count += 1

            if success_count % 10 == 0:
                self.stdout.write(f"Обработано {success_count} пользователей из {count}")

        self.stdout.write(self.style.SUCCESS(f'Успешно сгенерированы коды для {success_count} пользователей'))