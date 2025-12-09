from django.shortcuts import render, redirect
from django.contrib import messages
from django.db.models import Sum, Count
from django.utils import timezone
from django.http import JsonResponse
from decimal import Decimal

from .models import TokenSupply, TokenOperation
from trees.models import TonDistribution
from users.models import User

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User as AuthUser
from functools import wraps

def admin_login(request):
    """Функция для входа в админ-панель"""
    # Прямой вывод страницы входа, без перенаправления на Telegram аутентификацию
    
    # Если пользователь уже аутентифицирован и является суперпользователем
    if request.user.is_authenticated and request.user.is_superuser:
        return redirect('admin_dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        # Аутентификация пользователя
        user = authenticate(request, username=username, password=password)
        
        if user is not None and user.is_superuser:
            # Успешная аутентификация суперпользователя
            login(request, user)
            messages.success(request, 'Добро пожаловать в административную панель')
            return redirect('admin_dashboard')
        else:
            # Неудачная аутентификация
            messages.error(request, 'Неверные учетные данные или недостаточно прав')
    
    # Используем HttpResponse вместо render чтобы обойти перенаправление на аутентификацию
    from django.template.loader import render_to_string
    from django.http import HttpResponse
    
    html = render_to_string('admin_panel/login.html', {'messages': messages.get_messages(request)}, request=request)
    return HttpResponse(html)

def admin_logout(request):
    """Выход из админ-панели"""
    logout(request)
    messages.success(request, 'Вы успешно вышли из админ-панели')
    return redirect('admin_login')

def admin_required(view_func):
    """Декоратор для проверки, является ли пользователь администратором"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Проверка, авторизован ли пользователь и является ли он суперпользователем
        if not request.user.is_authenticated:
            messages.error(request, 'Вы должны авторизоваться')
            return redirect('admin_login')
            
        if not request.user.is_superuser:
            messages.error(request, 'Доступ запрещен: требуются права суперпользователя')
            return redirect('/')
            
        return view_func(request, *args, **kwargs)
    
    return wrapper

@admin_required
def admin_panel(request):
    """Главная страница админ-панели"""
    # Получаем статистику по токенам
    cf_total_supply = TokenSupply.get_current_supply()
    users_count = User.objects.count()
    cf_in_circulation = User.objects.aggregate(total=Sum('cf_balance'))['total'] or 0
    cf_staked = User.objects.aggregate(total=Sum('staking_cf'))['total'] or 0
    
    # Получаем последние операции
    recent_operations = TokenOperation.objects.all().order_by('-timestamp')[:10]
    
    # Активные раздачи TON
    active_ton_distributions = TonDistribution.objects.filter(is_active=True).order_by('-created_at')
    past_ton_distributions = TonDistribution.objects.filter(is_active=False).order_by('-created_at')[:5]
    
    context = {
        'cf_total_supply': cf_total_supply,
        'users_count': users_count,
        'cf_in_circulation': cf_in_circulation,
        'cf_staked': cf_staked,
        'recent_operations': recent_operations,
        'active_ton_distributions': active_ton_distributions,
        'past_ton_distributions': past_ton_distributions,
    }
    
    return render(request, 'admin_panel/index.html', context)

@admin_required
def burn_tokens(request):
    """Сжигание токенов"""
    if request.method == 'POST':
        try:
            amount = Decimal(request.POST.get('amount', 0))
            if amount <= 0:
                messages.error(request, 'Сумма должна быть больше нуля')
                return redirect('admin_panel')
                
            success, new_supply = TokenSupply.burn_tokens(amount)
            
            if success:
                messages.success(request, f'Успешно сожжено {amount} CF токенов. Новое количество: {new_supply}')
            else:
                messages.error(request, f'Недостаточно токенов для сжигания. Доступно: {new_supply}')
                
        except (ValueError, TypeError):
            messages.error(request, 'Некорректное значение для сжигания токенов')
            
    return redirect('admin_panel')

@admin_required
def create_ton_distribution(request):
    """Создание новой раздачи TON"""
    if request.method == 'POST':
        try:
            total_amount = Decimal(request.POST.get('total_amount', 0))
            duration_hours = int(request.POST.get('duration_hours', 24))
            
            if total_amount <= 0:
                messages.error(request, 'Сумма должна быть больше нуля')
                return redirect('admin_panel')
                
            if duration_hours <= 0:
                messages.error(request, 'Длительность должна быть больше нуля')
                return redirect('admin_panel')
            
            # Создаем новую раздачу TON
            distribution = TonDistribution.objects.create(
                total_amount=total_amount,
                duration_hours=duration_hours,
                is_active=True
            )
            
            # Записываем операцию
            TokenOperation.objects.create(
                operation_type='ton_distribution',
                amount=total_amount,
                description=f'Раздача {total_amount} TON на {duration_hours} часов'
            )
            
            messages.success(request, f'Создана новая раздача TON: {total_amount} TON на {duration_hours} часов')
            
        except (ValueError, TypeError):
            messages.error(request, 'Некорректные значения для раздачи TON')
            
    return redirect('admin_panel')

@admin_required
def get_token_stats(request):
    """API для получения статистики по токенам в реальном времени"""
    cf_total_supply = TokenSupply.get_current_supply()
    cf_in_circulation = User.objects.aggregate(total=Sum('cf_balance'))['total'] or 0
    cf_staked = User.objects.aggregate(total=Sum('staking_cf'))['total'] or 0
    
    return JsonResponse({
        'cf_total_supply': float(cf_total_supply),
        'cf_in_circulation': float(cf_in_circulation),
        'cf_staked': float(cf_staked),
        'timestamp': timezone.now().strftime('%d.%m.%Y %H:%M:%S'),
    })


def show_user_info(request):
    """Отображает информацию о пользователе для административных целей"""
    if not request.user:
        return JsonResponse({'error': 'Вы не авторизованы'}, status=403)
        
    # Информация о пользователе
    user_info = {
        'username': request.user.username,
        'telegram_id': request.user.telegram_id,
        'cf_balance': float(request.user.cf_balance),
        'ton_balance': float(request.user.ton_balance),
        'is_admin': str(request.user.telegram_id) == settings.ADMIN_USER_ID
    }
    
    # Дополнительная информация о настройках
    from django.conf import settings
    admin_info = {
        'admin_id_setting': settings.ADMIN_USER_ID,
        'match': str(request.user.telegram_id) == settings.ADMIN_USER_ID
    }
    
    return render(request, 'admin_panel/user_info.html', {
        'user_info': user_info,
        'admin_info': admin_info
    })
