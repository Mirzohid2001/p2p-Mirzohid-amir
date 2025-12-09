from django.urls import path
from . import views
from .views import check_task

urlpatterns = [
    path('', views.referral_program, name='referral_program'),
path('check_task/<int:task_id>/', check_task, name='check_task'),
] 