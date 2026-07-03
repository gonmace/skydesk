from django.urls import path

from . import views

app_name = 'tickets'

urlpatterns = [
    path('', views.board, name='board'),
    path('fragmento/', views.board_fragment, name='board_fragment'),
    path('mover/', views.ticket_move, name='move'),
    path('subticket/mover/', views.assignment_move, name='assignment_move'),
    path('subticket/<int:pk>/concluir/', views.assignment_conclude, name='assignment_conclude'),
    path('<int:pk>/aprobar/', views.ticket_approve, name='approve'),
    path('<int:pk>/rechazar/', views.ticket_reject, name='reject'),
    path('<int:pk>/suspender/', views.ticket_suspend, name='suspend'),
    path('mis-tickets/', views.my_tickets, name='my_tickets'),
    path('seguimiento/', views.seguimiento, name='seguimiento'),
    path('archivados/', views.archived, name='archived'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('<int:pk>/dividir/', views.ticket_divide, name='divide'),
    path('<int:pk>/derivar/', views.ticket_derive, name='derive'),
    path('<int:pk>/archivar/', views.ticket_archive, name='archive'),
    path('<int:pk>/desarchivar/', views.ticket_unarchive, name='unarchive'),
    path('etiquetas/', views.labels_manage, name='labels'),
    path('proyectos/', views.projects_manage, name='projects'),
    path('nuevo/', views.ticket_create, name='create'),
    path('adjunto/<int:pk>/', views.attachment_serve, name='attachment_serve'),
    path('adjunto/<int:pk>/thumb/', views.attachment_thumb, name='attachment_thumb'),
    path('adjunto/<int:pk>/borrar/', views.attachment_delete, name='attachment_delete'),
    path('comentario/<int:pk>/editar/', views.comment_edit, name='comment_edit'),
    path('comentario/<int:pk>/borrar/', views.comment_delete, name='comment_delete'),
    path('<int:pk>/', views.ticket_detail, name='detail'),
    path('<int:pk>/editar/', views.ticket_edit, name='edit'),
    path('<int:pk>/comentar/', views.comment_add, name='comment_add'),
    path('<int:pk>/adjuntar/', views.attachment_add, name='attachment_add'),
]
