import os
from celery import Celery
from django.conf import settings

# Django settings modulini o'rnatish
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crypto_backend.settings')

# Celery app yaratish
app = Celery('crypto_backend')

# Django settings'dan konfiguratsiya olish
app.config_from_object('django.conf:settings', namespace='CELERY')

# Django app'lardan task'larni avtomatik topish
app.autodiscover_tasks()

# Celery beat schedule (periodic tasks)
app.conf.beat_schedule = {
    # Har soat passiv CF taqsimlash
    'distribute-passive-cf': {
        'task': 'farm.tasks.distribute_passive_cf',
        'schedule': 3600.0,  # har soat
    },
    # Har kuni muddati tugagan orderlarni tekshirish
    'check-expired-orders': {
        'task': 'farm.tasks.order_timeout',
        'schedule': 86400.0,  # har kuni
    },
    # Haftada bir marta reklama daromadini taqsimlash
    'distribute-ad-profit': {
        'task': 'farm.tasks.distribute_ad_profit',
        'schedule': 604800.0,  # har hafta
    },
    # Har kuni muddati tugagan maxsus daraxtlarni deaktivatsiya qilish
    'deactivate-expired-special-trees': {
        'task': 'farm.tasks.deactivate_expired_special_trees',
        'schedule': 86400.0,  # har kuni
    },
}

app.conf.timezone = 'UTC'

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
