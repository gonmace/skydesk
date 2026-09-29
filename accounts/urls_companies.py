"""Rutas del panel de empresas (superuser) — se montan en /empresas/, sin prefijo."""
from django.urls import path

from . import views, views_companies

app_name = 'companies'

urlpatterns = [
    path('', views_companies.company_list, name='list'),
    path('nueva/', views_companies.company_create, name='create'),
    path('correo/', views.email_config, name='email_config'),
    path('<slug:slug>/editar/', views_companies.company_edit, name='edit'),
    path('<slug:slug>/miembros/agregar/', views_companies.company_member_add, name='member_add'),
    path('<slug:slug>/miembros/<int:pk>/quitar/', views_companies.company_member_remove, name='member_remove'),
]
