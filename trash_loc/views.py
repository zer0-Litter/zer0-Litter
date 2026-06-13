from django.shortcuts import render
from common.models import TrashLoc
from common.models_mongo import Complaints, Counter
from common.utils import bounding_box
from django.http import JsonResponse
import os
import logging
from math import radians, cos, sin, asin, sqrt
from django.contrib.auth.decorators import login_required
import json

logger = logging.getLogger(__name__)

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
    logger.debug(
        "trash_bin_list params - lat: %s, lon: %s, radius: %s",
        request.GET.get('lat'), request.GET.get('lon'), request.GET.get('radius'))

    try:
        lat = float(request.GET.get('lat'))
        lon = float(request.GET.get('lon'))
        radius = float(request.GET.get('radius', 500))  # 기본 500m
    except (TypeError, ValueError) as e:
        logger.warning("파라미터 변환 실패: %s", e)
        return JsonResponse({'error': 'Invalid parameters'}, status=400)

    # bounding-box 1차 필터로 후보를 좁힌 뒤 정확한 haversine 거리로 거른다(전수 스캔 회피)
    lat_min, lat_max, lon_min, lon_max = bounding_box(lat, lon, radius)
    candidates = TrashLoc.objects.filter(
        t_lat__gte=lat_min, t_lat__lte=lat_max,
        t_lon__gte=lon_min, t_lon__lte=lon_max,
    )

    nearby = []
    for t in candidates:
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
            logger.warning("쓰레기통 %s 처리 중 문제 발생: %s", t.id, e)
            continue  # 하나 실패해도 전체는 계속

    return JsonResponse(nearby, safe=False)


def haversine(lat1, lon1, lat2, lon2):
    """두 지점 간 거리 계산 (단위: m)"""
    R = 6371000  # 지구 반지름 (m)
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))


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


def generate_complaint_id():
    # com_id를 Counter로 원자적으로 발급 (max+1 방식의 동시성 중복키 충돌 방지)
    return Counter.objects(name="complaint").modify(upsert=True, new=True, inc__seq=1).seq