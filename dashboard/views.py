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
        # "$split"과 "$arrayElemAt"을 사용하여 구 이름을 정확히 추출
        pipeline = [
            {"$match": {"com_location": {"$regex": "^서울특별시"}}},
            {"$group": {
                "_id": {"$arrayElemAt": [{"$split": ["$com_location", " "]}, 1]},
                "count": {"$sum": 1}
            }}
        ]

        complaints_collection = Complaints._get_collection()
        district_counts_cursor = complaints_collection.aggregate(pipeline)

        # ❗❗ 딕셔너리로 변환, 키와 값을 모두 포함하도록 수정 ❗❗
        district_counts_dict = {item['_id'].strip(): item['count'] for item in district_counts_cursor}

        # 2. GeoJSON 파일 로드 및 데이터 병합
        geo_file_path = os.path.join(
            settings.BASE_DIR,
            'static', 'data', 'AL_D001_00_20250904(SIG)', 'AL_D001_00_20250904(SIG).shp'
        )

        gdf = gpd.read_file(geo_file_path, encoding='cp949')
        print(gdf.head())

        # 'A1' 컬럼의 값이 '11'로 시작하는 행만 선택하여 서울시 데이터로 필터링
        gdf = gdf[gdf['A1'].astype(str).str.startswith('11', na=False)].copy()

        # Timestamp 오류 해결을 위해 datetime 타입 컬럼을 문자열로 변환
        if 'A3' in gdf.columns and pd.api.types.is_datetime64_any_dtype(gdf['A3']):
            gdf['A3'] = gdf['A3'].astype(str)

        # 'A2' 컬럼의 '서울시' 문자열을 제거하여 데이터 매칭
        gdf['A2'] = gdf['A2'].str.replace('서울시', '', regex=False)

        # complaint_count 컬럼 추가
        gdf['complaint_count'] = gdf['A2'].map(district_counts_dict).fillna(0).astype(int)

        # 3. Folium 맵 생성
        m = folium.Map(location=[37.5665, 126.9780], zoom_start=11, tiles="cartodbpositron", width='100%',
                       height='100%')

        # Choropleth 레이어: 색상만 표시
        folium.Choropleth(
            geo_data=gdf,
            data=gdf,
            columns=['A2', 'complaint_count'],
            key_on='feature.properties.A2',
            fill_color='YlOrRd',
            fill_opacity=0.7,
            line_opacity=0.5,
            line_color='black',
            line_weight=1.5,
            legend_name='자치구별 쓰레기 민원 건수',
        ).add_to(m)

        # GeoJson 레이어: 툴팁을 통해 정보 표시
        folium.GeoJson(
            gdf,
            name='자치구 정보',
            tooltip=folium.GeoJsonTooltip(fields=['A2', 'complaint_count'], aliases=['자치구:', '민원 건수:']),
            style_function=lambda x: {'fillColor': 'transparent', 'color': 'transparent', 'weight': 0},
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