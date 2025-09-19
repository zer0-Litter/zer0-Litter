from django.http import HttpResponse
from django.shortcuts import render, redirect
from common.models import TrashLoc
from common.models_mongo import Complaints
from django.http import JsonResponse
import os
from math import radians, cos, sin, asin, sqrt
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
import json

# Create your views here.

def home(request):
    # 홈에서 신고 모달을 띄울 때 lat/lon 받아오기 (없으면 None)
    lat = request.GET.get("lat")
    lon = request.GET.get("lon")
    road_addr = request.GET.get("road_addr")

    return render(request, 'trash_loc/home.html', {
        'kakao_api_key': os.getenv('KAKAO_MAP_API_KEY'),
        'district_id': '11000',  # 테스트용, 실제는 request.user 등에 따라 결정
        'initial': {
            'lat': lat,
            'lon': lon,
            'location': road_addr,  # 도로명 주소
        }
    })

def trash_bin_map(request, district_id=None):
    if district_id:
        trashcans = TrashLoc.objects.filter(t_district_id=district_id)
    else:
        trashcans = TrashLoc.objects.all()

    data = [
        {
            "t_lat": float(t.t_lat),
            "t_lon": float(t.t_lon),
            "t_road_addr": t.t_addr,
            "t_detailed_addr": t.t_detailed_addr,
            "t_trash_type": t.t_trash_type,
            "t_loc": t.t_loc,
            "t_dept": t.t_dept,
            "t_contact": t.t_contact,
            "t_district_id": t.t_district_id,
        }
        for t in trashcans
    ]
    return JsonResponse(data, safe=False)



def trash_bin_list(request, district_id):
    print(
        f"Request Params - lat: {request.GET.get('lat')}, lon: {request.GET.get('lon')}, radius: {request.GET.get('radius')}")

    try:
        lat = float(request.GET.get('lat'))
        lon = float(request.GET.get('lon'))
        radius = float(request.GET.get('radius', 500))  # 기본 500m
    except (TypeError, ValueError) as e:
        print(f"[에러] 파라미터 변환 실패: {e}")
        return JsonResponse({'error': 'Invalid parameters'}, status=400)

    nearby = []
    for t in TrashLoc.objects.all():
        try:
            if not t.t_lat or not t.t_lon:
                continue  # 값이 None이거나 빈 문자열인 경우

            dist = haversine(lat, lon, float(t.t_lat), float(t.t_lon))
            if dist <= radius:
                nearby.append({
                    "t_lat": float(t.t_lat),
                    "t_lon": float(t.t_lon),
                    "t_road_addr": t.t_addr,
                    "t_detailed_addr": t.t_detailed_addr,
                    "t_trash_type": t.t_trash_type,
                    "t_loc": t.t_loc,
                    "t_dept": t.t_dept,
                    "t_contact": t.t_contact,
                })
        except Exception as e:
            print(f"[에러] 쓰레기통 {t.id} 처리 중 문제 발생: {e}")
            continue  # 하나 실패해도 전체는 계속

    return JsonResponse(nearby, safe=False)


def haversine(lat1, lon1, lat2, lon2):
    """두 지점 간 거리 계산 (단위: m)"""
    R = 6371000  # 지구 반지름 (m)
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))

from django.db import connection
print(connection.introspection.table_names())



@csrf_exempt
@login_required
def save_location(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            lat = data.get("lat")
            lon = data.get("lon")

            if lat is None or lon is None:
                return JsonResponse({"status": "error", "msg": "위치 데이터가 부족합니다"}, status=400)

            # Complaints에 저장
            from datetime import datetime
            Complaints(
                com_id=generate_complaint_id(),  # ✅ com_id는 직접 관리해야 한다고 하셨으니 별도 함수 필요
                username=request.user.username,
                com_type="location_report",      # ✅ 임시 타입 (상황에 맞게 변경)
                lat=float(lat),
                lon=float(lon),
                com_reg_date=datetime.utcnow()
            ).save()

            return JsonResponse({"status": "success"})
        except Exception as e:
            return JsonResponse({"status": "error", "msg": str(e)}, status=500)

    return JsonResponse({"status": "error", "msg": "POST 요청만 허용됩니다"}, status=405)

from common.models_mongo import Complaints



def generate_complaint_id():
    # com_id를 가장 큰 값 + 1 로 생성
    last = Complaints.objects.order_by("-com_id").first()
    return 1 if not last else last.com_id + 1