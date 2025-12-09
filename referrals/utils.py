# users/signals.py yoki referals/utils.py
from users.models import User
from .models import Referral, ReferralBonus

def create_referral(inviter, invited):
    referral, created = Referral.objects.get_or_create(inviter=inviter, invited=invited)
    if created:
        # Ro‘yxatdan o‘tgan bonus
        ReferralBonus.objects.create(
            referral=referral,
            bonus_type='signup',
            amount=10,  # masalan, 10 CF
            description="Бонус за регистрацию реферала"
        )

def get_telegram_user(request):
    tg_id = request.session.get("telegram_id")
    if not tg_id:
        return None
    try:
        return User.objects.get(telegram_id=tg_id)
    except User.DoesNotExist:
        return None