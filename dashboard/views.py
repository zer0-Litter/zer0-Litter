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
from folium.features import GeoJsonTooltip


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
        m = folium.Map(location=[37.5665, 126.9780], zoom_start=11, tiles="cartodbpositron", width='100%',
                       height='100%')

        sort_by = request.GET.get('sort_by')

        if sort_by == 'high' or sort_by == 'low':

            # 모든 지역을 회색으로 먼저 채움
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

                # 상위 5개 지역을 빨간색으로 강조
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

                # 하위 5개 지역을 파란색으로 강조
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
            # 전체: 민원 건수별 색상 그라데이션 및 범례 (Choropleth 사용)
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

            # 툴팁 추가
            folium.GeoJson(
                gdf,
                name='자치구 정보',
                tooltip=GeoJsonTooltip(fields=['A2', 'complaint_count'], aliases=['자치구:', '민원 건수:']),
                style_function=lambda x: {'fillColor': 'transparent', 'color': 'transparent', 'weight': 0},
            ).add_to(m)
            highlighted_title = "지도 위에 마우스를 올리면 민원 건수를 볼 수 있습니다."

        m.fit_bounds(m.get_bounds())

        map_html = m._repr_html_()

    except Exception as e:
        print(f"지도 생성 오류: {e}")
        map_html = "지도 생성에 오류가 발생했습니다."

    return render(request, "dashboard/dashboard.html", {
        "latest_complaints": latest,
        "map_html": map_html,
        "highlighted_list": highlighted_list,
        "highlighted_title": highlighted_title,
    })