# Crypto Farm - Django Template Project

Django template asosida qurilgan Crypto Farm loyihasi. Bu loyiha Telegram bot va web interface orqali virtual daraxt eking, suvlang va cryptocurrency ishlab chiqaring.

## 🚀 Xususiyatlar

- **🌱 Virtual Daraxt Tizimi**: Daraxt eking, suvlang va CF coin ishlab chiqaring
- **💱 P2P Savdo**: Foydalanuvchilar o'rtasida CF/TON/NOT savdosi
- **📈 Staking Tizimi**: CF coin'larni staking qiling va bonus oling
- **🎁 Referral Tizimi**: Do'stlaringizni taklif qiling va bonus oling
- **🤖 Telegram Bot**: Mini App bilan to'liq integratsiya
- **⚡ Real-time Notifications**: Telegram, email va web notifications
- **📊 Admin Panel**: To'liq boshqaruv paneli

## 🛠 Texnologiyalar

- **Backend**: Django 5.2
- **Database**: PostgreSQL
- **Cache & Queue**: Redis + Celery
- **Bot**: python-telegram-bot
- **Frontend**: Django Templates (HTML/CSS/JS)

## 📋 Talablar

- Python 3.8+
- PostgreSQL 12+
- Redis 6+
- Telegram Bot Token

## ⚙️ O'rnatish

### 1. Repository clone qiling
```bash
git clone <repository-url>
cd Floriya-p2p/backend
```

### 2. Virtual environment yarating
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# yoki
venv\Scripts\activate  # Windows
```

### 3. Dependencies o'rnating
```bash
pip install -r requirements.txt
```

### 4. Environment variables sozlang
`.env` fayl yarating:
```env
# Django
DEBUG=True
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=localhost,127.0.0.1

# Database
POSTGRES_DB=crypto_farm
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your-password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# Redis & Celery
REDIS_URL=redis://localhost:6379/1
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Telegram Bot
TG_BOT_TOKEN=your-telegram-bot-token
WEBAPP_URL=http://localhost:8000

# Email (ixtiyoriy)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
DEFAULT_FROM_EMAIL=noreply@cryptofarm.com
ADMIN_EMAIL=admin@cryptofarm.com

# Crypto Settings
SYSTEM_TON_WALLET=your-ton-wallet-address
CURRENT_CF_PRICE=0.001
```

### 5. Database sozlang
```bash
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
```

### 6. Static fayllarni yig'ing
```bash
python manage.py collectstatic
```

## 🚀 Ishga tushirish

### Development rejimi

1. **Django server**:
```bash
python manage.py runserver
```

2. **Celery worker** (yangi terminal):
```bash
celery -A crypto_backend worker --loglevel=info
```

3. **Celery beat** (yangi terminal):
```bash
celery -A crypto_backend beat --loglevel=info
```

4. **Telegram bot** (yangi terminal):
```bash
python manage.py run_telegram_bot
```

### Production rejimi

1. **Gunicorn bilan Django**:
```bash
gunicorn crypto_backend.wsgi:application --bind 0.0.0.0:8000
```

2. **Celery worker**:
```bash
celery -A crypto_backend worker --loglevel=info --detach
```

3. **Celery beat**:
```bash
celery -A crypto_backend beat --loglevel=info --detach
```

4. **Telegram bot**:
```bash
python manage.py run_telegram_bot --background
```

## 📁 Loyiha tuzilishi

```
backend/
├── crypto_backend/          # Django settings
│   ├── settings.py
│   ├── urls.py
│   ├── celery.py
│   └── wsgi.py
├── farm/                    # Asosiy app
│   ├── models.py           # Database modellari
│   ├── views.py            # Template views
│   ├── urls.py             # URL routing
│   ├── admin.py            # Admin interface
│   ├── tasks.py            # Celery tasks
│   ├── services.py         # Business logic
│   ├── templates/          # HTML templates
│   ├── static/             # CSS, JS, images
│   ├── management/         # Django commands
│   └── utils/              # Utility functions
├── run_bot.py              # Telegram bot
├── requirements.txt        # Dependencies
└── README.md              # Bu fayl
```

## 🎮 Foydalanish

### Web Interface
1. Brauzerda `http://localhost:8000` ga o'ting
2. Admin panel: `http://localhost:8000/admin/`

### Telegram Bot
1. Telegram'da botingizni toping
2. `/start` buyrug'ini yuboring
3. "🚀 Crypto Farm ochish" tugmasini bosing

## 🔧 Asosiy Funksiyalar

### Daraxt Tizimi
- Daraxt eking va level'ini oshiring
- 5 soat davomida bepul poliv
- Auto-poliv xususiyati
- Fertilizer bilan 2x bonus

### P2P Savdo
- CF/TON/NOT coin'larni savdo qiling
- Real-time order matching
- Avtomatik komissiya hisoblash

### Staking
- CF coin'larni staking qiling
- Turli muddat va foiz stavkalari
- Avtomatik bonus hisoblash

### Notifications
- Telegram bot orqali real-time xabarlar
- Email notifications
- Web interface notifications

## 📊 Admin Panel

Django admin panel orqali:
- Foydalanuvchilarni boshqaring
- Tranzaksiyalarni kuzating
- Orderlarni nazorat qiling
- Statistikalarni ko'ring

## 🔄 Celery Tasks

Avtomatik ishlaydigan vazifalar:
- **Har soat**: Passiv CF taqsimlash
- **Kunlik**: Expired orderlarni tekshirish
- **Haftalik**: Reklama daromadini taqsimlash
- **Kunlik**: Statistika yuborish

## 🐛 Debug

### Loglar
```bash
# Django logs
tail -f debug.log

# Celery logs
celery -A crypto_backend events

# Bot logs
python run_bot.py
```

### Test
```bash
# Django testlar
python manage.py test

# Specific test
python manage.py test farm.tests.ViewSyntaxTestCase
```

## 🚀 Deploy

### Docker (ixtiyoriy)
```bash
# Docker image yaratish
docker build -t crypto-farm .

# Container ishga tushirish
docker run -p 8000:8000 crypto-farm
```

### Nginx konfiguratsiyasi
```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    
    location /static/ {
        alias /path/to/static/files/;
    }
}
```

## 🤝 Hissa qo'shish

1. Fork qiling
2. Feature branch yarating
3. Commit qiling
4. Pull request yuboring

## 📄 Litsenziya

MIT License

## 📞 Qo'llab-quvvatlash

- Email: support@cryptofarm.com
- Telegram: @crypto_farm_support
- Issues: GitHub Issues 