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

app_name = 'complain'

urlpatterns = [
    path('complain_add/', views.complain_add, name='complain_add'),
    path('reuse/<int:com_id>/', views.complain_reuse, name='complain_reuse'), # 재민원처리
    path('api/my-complaints/', views.old_complaints_api, name='old_complaints_api'), # 이전민원확인하기
    path("manage/all/", views.all_complaints_staff, name="staff_all_list"),          # 관리자
    path("manage/pending/", views.pending_list, name="pending_list"),          # 처리중
    path("manage/<int:com_id>/complete/", views.mark_complaint_completed, name="mark_completed"),  # 완료처리
    path("manage/completed/", views.completed_list, name="completed_list"),
]
