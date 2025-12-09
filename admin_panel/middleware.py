class AdminPanelMiddleware:
    """Middleware для обработки запросов к админ-панели"""
    
    def __init__(self, get_response):
        self.get_response = get_response
        
    def __call__(self, request):
        # Проверяем, является ли запрос к админ-панели
        if request.path.startswith('/admin-panel/'):
            # Устанавливаем флаг, что это запрос к админ-панели
            request.admin_panel_request = True
            
        response = self.get_response(request)
        return response
