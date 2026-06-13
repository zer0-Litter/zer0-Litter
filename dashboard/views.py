# dashboard/views.py

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timezone as py_tz
from common.models_mongo import Complaints
from django.conf import settings
import folium
import geopandas as gpd
import os
import re
import json
import logging
import pandas as pd
from folium.features import GeoJsonTooltip

logger = logging.getLogger(__name__)


# Django 캐싱 관련 라이브러리 제거
# from django.core.cache import cache

def _timeago_kor(dt):
    if not dt:
        return ""
    if timezone.is_naive(dt):
        dt = dt.replace(tzinfo=py_tz.utc)
    now = timezone.now()
    diff = now - dt
    secs = int(diff.total_seconds())
    if secs < 60:
        return "방금 전"
    mins = secs // 60
    if mins < 60:
        return f"{mins}분 전"
    hours = mins // 60
    if hours < 24:
        return f"{hours}시간 전"
    days = hours // 24
    if days < 7:
        return f"{days}일 전"
    weeks = days // 7
    return f"{weeks}주 전"


def _get_day_of_week_counts():
    """
    MongoDB에서 직접 요일별 민원 건수를 가져오는 함수
    """
    logger.debug("요일별 민원 데이터 계산 중...")
    pipeline = [
        {"$group": {
            "_id": {"$dayOfWeek": "$com_reg_date"},
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id": 1}}
    ]
    counts_cursor = Complaints._get_collection().aggregate(pipeline)

    day_map = {1: '일', 2: '월', 3: '화', 4: '수', 5: '목', 6: '금', 7: '토'}
    day_counts = {day_map[i]: 0 for i in range(1, 8)}
    for item in counts_cursor:
        day_counts[day_map[item['_id']]] = item['count']

    day_labels_json = json.dumps(list(day_counts.keys()))
    day_counts_json = json.dumps(list(day_counts.values()))

    logger.debug("요일별 민원 데이터 계산 완료")

    return day_labels_json, day_counts_json


def get_avg_response_time():
    """민원 평균 응답 시간을 계산하는 함수"""
    pipeline = [
        {"$lookup": {
            "from": "complaint_status",
            "localField": "com_id",
            "foreignField": "com_id",
            "as": "statuses"
        }},
        {"$unwind": "$statuses"},
        {"$match": {"statuses.status_name": "처리완료"}},
        {"$addFields": {
            "response_time_ms": {
                "$subtract": ["$statuses.updated_at", "$com_reg_date"]
            }
        }},
        {"$group": {
            "_id": {"$arrayElemAt": [{"$split": ["$com_location", " "]}, 1]},
            "avg_time_ms": {"$avg": "$response_time_ms"}
        }},
        {"$match": {"_id": {"$exists": True, "$ne": "서울특별시"}}}
    ]

    avg_times_cursor = Complaints._get_collection().aggregate(pipeline)

    avg_times = []
    for item in avg_times_cursor:
        if item.get('avg_time_ms') is None or item.get('avg_time_ms') < 0:
            continue

        district = item['_id']
        total_seconds = item['avg_time_ms'] / 1000

        # --- 여기서 일, 시간, 분으로 변환 ---
        days = int(total_seconds // 86400)
        hours = int((total_seconds % 86400) // 3600)
        minutes = int((total_seconds % 3600) // 60)

        time_str = ""
        if days > 0:
            time_str += f"{days}일 "
        if hours > 0:
            time_str += f"{hours}시간 "
        time_str += f"{minutes}분"

        avg_times.append({
            'district': district,
            'time': time_str,
            'seconds': total_seconds
        })

    if not avg_times:
        return None, None

    avg_times.sort(key=lambda x: x['seconds'])

    fastest = avg_times[0]
    slowest = avg_times[-1]

    return fastest, slowest


@login_required(login_url='accounts:login')
def dashboard(request):
    qs = Complaints.objects.order_by("-com_reg_date").limit(3)
    latest = []
    for c in qs:
        region = c.com_location or "서울특별시"
        type_label = (c.com_type or "").strip()
        timeago = _timeago_kor(c.com_reg_date)

        complaint_type = c.com_type
        if isinstance(complaint_type, list):
            icon_type = complaint_type[0] if complaint_type else "기타"
        else:
            icon_type = (complaint_type.split(",")[0].strip()
                         if complaint_type else "기타")

        latest.append({
            "region": region,
            "type_label": type_label,
            "timeago": timeago,
            "icon_type": icon_type,
        })

    map_html = None
    highlighted_list = []
    highlighted_title = ""

    try:
        # 1. MongoDB에서 자치구별 민원 건수 집계
        pipeline = [
            {"$match": {"com_location": {"$regex": "^서울특별시"}}},
            {"$group": {
                "_id": {"$arrayElemAt": [{"$split": ["$com_location", " "]}, 1]},
                "count": {"$sum": 1}
            }}
        ]

        complaints_collection = Complaints._get_collection()
        district_counts_cursor = complaints_collection.aggregate(pipeline)
        district_counts_dict = {item['_id'].strip(): item['count'] for item in district_counts_cursor}

        # 2. GeoJSON 파일 로드 및 데이터 병합
        geo_file_path = os.path.join(
            settings.BASE_DIR,
            'static', 'data', 'AL_D001_00_20250904(SIG)', 'AL_D001_00_20250904(SIG).shp'
        )

        gdf = gpd.read_file(geo_file_path, encoding='cp949')
        gdf = gdf[gdf['A1'].astype(str).str.startswith('11', na=False)].copy()

        if 'A3' in gdf.columns and pd.api.types.is_datetime64_any_dtype(gdf['A3']):
            gdf['A3'] = gdf['A3'].astype(str)

        gdf['A2'] = gdf['A2'].str.replace('서울시', '', regex=False)
        gdf['complaint_count'] = gdf['A2'].map(district_counts_dict).fillna(0).astype(int)

        # 3. Folium 맵 생성
        m = folium.Map(location=[37.5665, 126.9780], zoom_start=11, tiles="cartodbpositron",
                       width='100%', height='100%', zoom_control=False)

        sort_by = request.GET.get('sort_by')

        if sort_by == 'high' or sort_by == 'low':
            folium.GeoJson(
                gdf,
                style_function=lambda x: {
                    'fillColor': '#d3d3d3',
                    'color': 'black',
                    'weight': 1.5,
                    'fillOpacity': 0.7,
                }
            ).add_to(m)

            if sort_by == 'high':
                top5 = gdf.nlargest(5, 'complaint_count')
                folium.GeoJson(
                    top5,
                    style_function=lambda x: {
                        'fillColor': '#b40424',
                        'color': 'black',
                        'weight': 1.5,
                        'fillOpacity': 1.0,
                    },
                    tooltip=GeoJsonTooltip(fields=['A2', 'complaint_count'], aliases=['자치구:', '민원 건수:']),
                ).add_to(m)
                highlighted_list = top5[['A2', 'complaint_count']].rename(
                    columns={'A2': 'district', 'complaint_count': 'count'}).to_dict('records')
                highlighted_title = "민원이 많은 지역구 목록"
            elif sort_by == 'low':
                bottom5 = gdf.nsmallest(5, 'complaint_count')
                folium.GeoJson(
                    bottom5,
                    style_function=lambda x: {
                        'fillColor': '#3186cc',
                        'color': 'black',
                        'weight': 1.5,
                        'fillOpacity': 1.0,
                    },
                    tooltip=GeoJsonTooltip(fields=['A2', 'complaint_count'], aliases=['자치구:', '민원 건수:']),
                ).add_to(m)
                highlighted_list = bottom5[['A2', 'complaint_count']].rename(
                    columns={'A2': 'district', 'complaint_count': 'count'}).to_dict('records')
                highlighted_title = "민원이 적은 지역구 목록"
        else:
            folium.Choropleth(
                geo_data=gdf,
                data=gdf,
                columns=['A2', 'complaint_count'],
                key_on='feature.properties.A2',
                fill_color='YlOrRd',
                fill_opacity=0.7,
                line_opacity=0.5,
                line_color='black',
                line_weight=1.0,
                legend_name='자치구별 쓰레기 민원 건수',
                show_colorbar=True
            ).add_to(m)

            folium.GeoJson(
                gdf,
                name='자치구 정보',
                tooltip=GeoJsonTooltip(fields=['A2', 'complaint_count'], aliases=['자치구:', '민원 건수:']),
                style_function=lambda x: {'fillColor': 'transparent', 'color': 'transparent', 'weight': 0},
            ).add_to(m)
            highlighted_title = "지도 위에 마우스를 올리면 민원 건수를 볼 수 있습니다."

        m.fit_bounds(m.get_bounds())
        map_html = m._repr_html_()

        # --- HTML 문자열 직접 수정 (범례 위치 및 스타일 조정) ---
        if map_html and "branca-linear-cmap" in map_html:
            map_html = map_html.replace(
                '<div class="leaflet-control-container">',
                '<div class="leaflet-control-container" style="position: absolute; top: 0; right: 0;">'
            )
            map_html = re.sub(
                r'(<svg[^>]*width="[^"]*"[^>]*height="[^"]*"[^>]*>)([\s\S]*?)(</svg>)',
                r'<svg width="150" height="20" style="position:absolute; right:10px;">\2</svg>',
                map_html
            )
            map_html = re.sub(
                r'<text x="0.0%"[^>]*>([^<]+)</text>',
                r'<text x="5%" style="font-size: 10px; text-anchor: middle;">\1</text>',
                map_html
            )
            map_html = re.sub(
                r'<text x="100.0%"[^>]*>([^<]+)</text>',
                r'<text x="95%" style="font-size: 10px; text-anchor: middle;">\1</text>',
                map_html
            )

    except Exception as e:
        logger.error("지도 생성 오류: %s", e, exc_info=True)
        map_html = "지도 생성에 오류가 발생했습니다."

    # --- 기존 코드 수정: 캐싱 함수 호출 ---
    # Redis 캐싱 함수를 직접 데이터 가져오는 함수로 변경
    day_labels_json, day_counts_json = _get_day_of_week_counts()

    logger.debug("차트 데이터 - labels=%s, counts=%s", day_labels_json, day_counts_json)

    fastest_district, slowest_district = get_avg_response_time()

    if not fastest_district:
        fastest_district = {'district': '-', 'time': '데이터 없음'}
    if not slowest_district:
        slowest_district = {'district': '-', 'time': '데이터 없음'}

    logger.debug(
        "대시보드 데이터 - day_counts=%s, fastest=%s, slowest=%s",
        day_counts_json, fastest_district, slowest_district)

    # 갱신 시간 정보는 더 이상 Redis에서 가져오지 않으므로, 현재 시간으로 설정
    last_updated_time = timezone.now().strftime('%Y년 %m월 %d일 %H시 %M분')

    return render(request, "dashboard/dashboard.html", {
        "latest_complaints": latest,
        "map_html": map_html,
        "highlighted_list": highlighted_list,
        "highlighted_title": highlighted_title,
        "day_counts": day_counts_json,
        "day_labels": day_labels_json,
        "fastest_district": fastest_district,
        "slowest_district": slowest_district,
        "last_updated_time": last_updated_time,  # 갱신 시간 추가
    })