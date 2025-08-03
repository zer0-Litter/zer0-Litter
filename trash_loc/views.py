from django.http import HttpResponse
from django.shortcuts import render
from common.models import TrashLoc
from django.http import JsonResponse
import os
from math import radians, cos, sin, asin, sqrt
# Create your views here.

def home(request):
    return render(request, 'trash_loc/home.html', {
        'kakao_api_key': os.getenv('KAKAO_MAP_API_KEY'),
        'district_id': '11000'  # 테스트용, 실제는 request.user 등에 따라 결정
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
            "t_road_addr": t.t_road_addr,
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
                    "t_road_addr": t.t_road_addr,
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
