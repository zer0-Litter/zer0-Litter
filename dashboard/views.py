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

# pandas 모듈을 사용하여 데이터 타입을 변환합니다.
import pandas as pd


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


@login_required(login_url='accounts:login')
def dashboard(request):
    # 기존 실시간 민원 현황 로직 (변화 없음)
    qs = Complaints.objects.order_by("-com_reg_date").limit(3)
    latest = []
    for c in qs:
        region = c.com_location or "서울특별시"
        type_label = (c.com_type or "").strip()
        timeago = _timeago_kor(c.com_reg_date)
        latest.append({
            "region": region,
            "type_label": type_label,
            "timeago": timeago,
        })

    # ------------------ 쓰레기 민원 지도 추가 로직 시작 ------------------
    map_html = None
    try:
        # 1. MongoDB에서 자치구별 민원 건수 집계
        pipeline = [
            {"$match": {"com_location": {"$regex": "^서울특별시"}}},
            {"$group": {
                "_id": {"$substr": ["$com_location", 6, -1]},
                "count": {"$sum": 1}
            }}
        ]

        complaints_collection = Complaints._get_collection()
        district_counts_cursor = complaints_collection.aggregate(pipeline)

        # 딕셔너리로 변환
        district_counts = {item['_id'] + '구': item['count'] for item in district_counts_cursor}

        # ❗❗ GET 요청 파라미터로 정렬 기준을 가져와서 데이터 정렬 ❗❗
        sort_by = request.GET.get('sort_by', 'all')
        if sort_by == 'high':
            # count를 기준으로 내림차순 정렬
            sorted_counts = sorted(district_counts.items(), key=lambda item: item[1], reverse=True)
            district_counts = dict(sorted_counts)
        elif sort_by == 'low':
            # count를 기준으로 오름차순 정렬
            sorted_counts = sorted(district_counts.items(), key=lambda item: item[1])
            district_counts = dict(sorted_counts)

        # 2. GeoJSON 파일 로드 및 데이터 병합
        geo_file_path = os.path.join(
            settings.BASE_DIR,
            'static', 'data', 'AL_D001_00_20250904(SIG)', 'AL_D001_00_20250904(SIG).shp'
        )

        gdf = gpd.read_file(geo_file_path, encoding='cp949')
        #print(gdf.head())

        # 'A1' 컬럼의 값이 '11'로 시작하는 행만 선택하여 서울시 데이터로 필터링
        gdf = gdf[gdf['A1'].astype(str).str.startswith('11', na=False)].copy()

        gdf['district_name'] = gdf['A2'].apply(lambda x: x.strip())

        # 정렬된 데이터를 다시 gdf에 매핑
        gdf['complaint_count'] = gdf['district_name'].map(district_counts).fillna(0)

        # A3 컬럼이 datetime 형식일 수 있으므로 문자열로 변환
        if 'A3' in gdf.columns:
            gdf['A3'] = gdf['A3'].astype(str)

        # 3. Folium 맵 생성
        # 지도의 초기 크기를 100%로 설정하여 부모 요소에 꽉 차도록 함
        m = folium.Map(location=[37.5665, 126.9780], zoom_start=11, tiles="cartodbpositron", width='100%',
                       height='100%')

        # 민원 건수 분포를 명확하게 보여주기 위해 bins(구간) 설정
        # (이 값은 실제 민원 건수 분포에 따라 조정될 수 있습니다.)
        bins = [0, 1, 2, 5, 10, 20]

        folium.Choropleth(
            geo_data=gdf,
            data=gdf,
            columns=['district_name', 'complaint_count'],
            key_on='feature.properties.A2',
            fill_color='YlOrRd',
            fill_opacity=0.7,
            line_opacity=0.5,
            line_color='black',  # 경계선 색상 추가
            line_weight=1.5,  # 경계선 두께 추가
            legend_name='자치구별 쓰레기 민원 건수',
            tooltip=folium.GeoJsonTooltip(fields=['A2', 'complaint_count'], aliases=['자치구:', '민원 건수:']),
            # bins 파라미터를 추가하여 색상 구간을 명확히 설정
            bins=bins
        ).add_to(m)

        map_html = m._repr_html_()

    except Exception as e:
        print(f"지도 생성 오류: {e}")
        map_html = "지도 생성에 오류가 발생했습니다."
    # ------------------ 쓰레기 민원 지도 추가 로직 끝 ------------------

    return render(request, "dashboard/dashboard.html", {
        "latest_complaints": latest,
        "map_html": map_html,
    })