from django.shortcuts import render, redirect
from django.http import HttpResponse
from .models import TrashLoc

# Create your views here.

# 메인 소개 페이지
# GET /home/
def home(request):
    return render(request, 'trash_loc/home.html')

# 지도 기반 쓰레기통 위치 추천
# GET /trash_loc/map/<str:district_idx>/
def trash_bin_map(request, district_idx):
    return render(request, 'trash_loc/home.html', {'district_idx': district_idx})

# 쓰레기통 목록 조회
# GET /trash_loc/list/<str:district_idx>/
def trash_bin_list(request, district_idx):
    return render(request, 'trash_loc/home.html', {'district_idx': district_idx})

# 클릭 시 쓰레기통 상세 모달 정보
# GET /trash_bin/<int:bin_id>/detail/
def trash_bin_detail(request, bin_id):
    return render(request, 'trash_loc/home.html', {'bin_id': bin_id})

# 신고 페이지(리다이렉트)
# GET /complain/<int:bin_id>/
def complain(request, bin_id):
    return redirect('/complain/complain_add/')

# 테스트용! 작업할 땐 지우고 사용해주세요 (html도 포함!)
# def trash_loc_list(request):
#     trash_locs = TrashLoc.objects.all()
#     return render(request, 'trash_loc_list.html', {'trash_locs': trash_locs})
