from django.urls import path
from . import views

app_name = 'chatbot'

urlpatterns = [
    path('chatbot_api/', views.chatbot_api, name='chatbot_api'),
    # path('<int:scenario_id>/chatbot_chat/', views.chatbot_api, name='chatbot_chat'),
    path('chatbot_chat_default/', views.chatbot_chat_default, name='chatbot_chat_default'),
    path('trash_loc/list/<str:district_id>/', views.trash_bin_list, name='trash_bin_list'),
    path('trash_loc/map/<str:district_id>/', views.trash_bin_map, name='trash_bin_map'),
]
