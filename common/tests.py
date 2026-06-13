"""common.utils 순수 함수 테스트."""
from common.utils import normalize_com_types, bounding_box


# ---------- normalize_com_types ----------

def test_normalize_from_comma_string():
    assert normalize_com_types("청소요청, 기타") == ["청소요청", "기타"]


def test_normalize_from_list():
    assert normalize_com_types([" 청소요청 ", "", "수리요청"]) == ["청소요청", "수리요청"]


def test_normalize_none_and_empty():
    assert normalize_com_types(None) == []
    assert normalize_com_types("") == []
    assert normalize_com_types([]) == []


# ---------- bounding_box ----------

def test_bounding_box_contains_center():
    lat, lon = 37.5665, 126.9780
    lat_min, lat_max, lon_min, lon_max = bounding_box(lat, lon, 500)
    assert lat_min < lat < lat_max
    assert lon_min < lon < lon_max


def test_bounding_box_latitude_delta():
    # 위도 delta 는 반경/111320 (m→도). 500m ≈ 0.00449도
    lat_min, lat_max, _, _ = bounding_box(37.5, 127.0, 500)
    assert abs((lat_max - lat_min) - 2 * (500 / 111320.0)) < 1e-9


def test_bounding_box_longitude_wider_than_latitude_at_mid_lat():
    # 중위도에서는 경도 1도가 더 짧으므로(cos), 같은 반경에 대한 경도 delta 가 위도 delta 보다 크다
    lat_min, lat_max, lon_min, lon_max = bounding_box(37.5, 127.0, 500)
    assert (lon_max - lon_min) > (lat_max - lat_min)
