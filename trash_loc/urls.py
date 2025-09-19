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
from complain import views as complain_views

app_name = 'trash_loc'

urlpatterns = [
    path('', views.home, name='home'),
    path('trash_loc/map/<str:district_id>/', views.trash_bin_map, name='trash_bin_map'),  # 지도 기반 추천
    path('trash_loc/list/<str:district_id>/', views.trash_bin_list, name='trash_bin_list'),  # 목록 조회
    # path('trash_bin/<int:bin_id>/detail/', views.trash_bin_detail, name='trash_bin_detail'),  # 상세 정보
    # path('complain/<int:bin_id>/', views.complain, name='complain'),  # 민원 페이지
    path("save_location/", views.save_location, name="save_location"),
    path('complain_add/', complain_views.complain_add, name='complain_add'),

]
