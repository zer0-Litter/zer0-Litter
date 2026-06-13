"""공통 유틸리티."""
from math import radians, cos


def bounding_box(lat, lon, radius_m):
    """중심(lat, lon)에서 반경 radius_m(미터)를 포함하는 위경도 사각 범위를 돌려준다.

    반환: (lat_min, lat_max, lon_min, lon_max)
    근접 검색에서 DB 1차 필터로 사용 → 전수 스캔/전건 haversine 계산을 줄인다.
    (사각형이라 모서리는 반경보다 멀 수 있으나, 이후 정확한 haversine 거리 필터로 걸러진다.)
    """
    lat_delta = radius_m / 111_320.0          # 위도 1도 ≈ 111.32km
    cos_lat = cos(radians(lat))
    if abs(cos_lat) < 1e-12:
        cos_lat = 1e-12                        # 극점 부근 0 division 방지
    lon_delta = radius_m / (111_320.0 * abs(cos_lat))
    return lat - lat_delta, lat + lat_delta, lon - lon_delta, lon + lon_delta


def normalize_com_types(value):
    """민원 유형(com_type)을 정규화된 문자열 리스트로 변환한다.

    - 리스트: 각 항목 strip 후 빈 값 제거
    - 콤마 문자열("청소요청, 기타"): 콤마로 분리 후 strip/빈 값 제거
    - None/빈 값: 빈 리스트

    여러 뷰에 흩어져 있던 동일 파싱 로직을 한 곳으로 모은 것.
    """
    if isinstance(value, list):
        items = value
    else:
        items = str(value or "").split(",")
    return [str(t).strip() for t in items if str(t).strip()]
