from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, Http404
from .models import TrashLoc

# 메인 소개 페이지
# GET /home/
def home(request):
    return render(request, 'trash_loc/home.html')

# 지도 기반 쓰레기통 위치 추천
# GET /trash_loc/map/<str:district_idx>/
def trash_bin_map(request, district_idx):
    # district_idx가 유효하지 않을 경우 예외 처리
    if not district_idx:
        # 잘못된 요청 처리
        return HttpResponse('구 정보를 찾을 수 없습니다.'.encode('utf-8'), status=400)
    # 실제 데이터 연동은 추후 구현
    return render(request, 'trash_loc/home.html', {'district_idx': district_idx})

# 쓰레기통 목록 조회
# GET /trash_loc/list/<str:district_idx>/
def trash_bin_list(request, district_idx):
    if not district_idx:
        return HttpResponse('구 정보를 찾을 수 없습니다.'.encode('utf-8'), status=400)
    # 실제 데이터 연동은 추후 구현
    return render(request, 'trash_loc/home.html', {'district_idx': district_idx})

# 클릭 시 쓰레기통 상세 모달 정보
# GET /trash_bin/<int:bin_id>/detail/
def trash_bin_detail(request, bin_id):
    # bin_id가 실제 존재하는지 확인, 없으면 404 반환
    try:
        trash_bin = TrashLoc.objects.get(pk=bin_id)
    except TrashLoc.DoesNotExist:
        raise Http404('해당 쓰레기통 정보를 찾을 수 없습니다.')
    # 실제 상세 정보 연동은 추후 구현
    return render(request, 'trash_loc/home.html', {'bin_id': bin_id, 'trash_bin': trash_bin})

# 신고 페이지(리다이렉트)
# GET /complain/<int:bin_id>/
def complain(request, bin_id):
    # bin_id가 실제 존재하는지 확인, 없으면 404 반환
    try:
        TrashLoc.objects.get(pk=bin_id)
    except TrashLoc.DoesNotExist:
        raise Http404('해당 쓰레기통 정보를 찾을 수 없습니다.')
    # 실제 신고 페이지로 리다이렉트
    return redirect('/complain/complain_add/')
