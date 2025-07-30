"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.urls import path
from . import views  # 뷰가 있으면 import

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login, name='login'), #로그인 페이지
    path('logout/', views.logout_view, name='logout'),
    path('check_user_id/',views.check_user_id, name='check_user_id'),
    path('check-password/', views.check_password_api, name='check_password'),
    path('login/submit/', views.LoginView.as_view(), name='login_view'), #로그인 처리
    path('register/', views.RegisterView.as_view(),name='register'), #회원가입 페이지
    path('mypage_home/', views.mypage_home, name='mypage_home'),
    path('mypage/edit/', views.mypage_edit, name='mypage_edit'),
    path('mypage/update/', views.mypage_update, name='mypage_update'),
    path('delete/', views.delete_user, name='delete_user'),
    path('complaint_all/', views.complaint_all_list, name='complaint_all'),
]
