def user_balances(request):
    user = getattr(request, 'user', None)
    if user and hasattr(user, 'cf_balance') and hasattr(user, 'ton_balance'):
        return {
            'cf_balance': user.cf_balance,
            'ton_balance': user.ton_balance,
        }
    return {
        'cf_balance': 0,
        'ton_balance': 0,
    }