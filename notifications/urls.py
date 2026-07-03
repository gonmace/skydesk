from django.urls import path

from . import views

app_name = 'notifications'

urlpatterns = [
    path('', views.notifications_list, name='list'),
    path('menu/', views.menu_fragment, name='menu_fragment'),
    path('<int:pk>/abrir/', views.open_notification, name='open'),
    path('marcar-todas/', views.mark_all_read, name='mark_all_read'),
]
