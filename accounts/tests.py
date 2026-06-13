"""accounts 앱 테스트: 비밀번호 검증 로직 + 계정 열거 방지 로그인."""
import pytest
from rest_framework import serializers

from accounts.serializers import UserRegisterSerializer
from accounts.views import is_valid_password


# ---------- 순수 검증 로직 (DB 불필요) ----------

def test_register_password_mismatch():
    s = UserRegisterSerializer()
    with pytest.raises(serializers.ValidationError):
        s.validate({"password": "Abcdef1!", "password2": "Different1!"})


def test_register_password_too_weak():
    s = UserRegisterSerializer()
    with pytest.raises(serializers.ValidationError):
        s.validate({"password": "weak", "password2": "weak"})


def test_register_password_ok():
    s = UserRegisterSerializer()
    out = s.validate({"password": "Abcdef1!", "password2": "Abcdef1!"})
    assert out["password"] == "Abcdef1!"


@pytest.mark.parametrize("pw,expected", [
    ("Abcdef1!", True),    # 8자+숫자+특수
    ("short1!", False),    # 8자 미만
    ("noDigits!", False),  # 숫자 없음
    ("nodigit12", False),  # 특수문자 없음
])
def test_is_valid_password(pw, expected):
    assert is_valid_password(pw) is expected


# ---------- 로그인 플로우 (SQLite, 계정 열거 방지) ----------

def _make_user(**kwargs):
    from common.models import Users
    defaults = dict(
        username="kim", name="김철수", birth="1990-01-01",
        gender="M", address="서울특별시 중구", phone_number="01000000000",
    )
    defaults.update(kwargs)
    pw = defaults.pop("password", "Abcdef1!")
    return Users.objects.create_user(password=pw, **defaults)


@pytest.mark.django_db
def test_login_success(client):
    _make_user(username="kim", password="Abcdef1!")
    r = client.post("/accounts/login/submit/", {"username": "kim", "password": "Abcdef1!"})
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "kim"
    assert "access" in body and "refresh" in body


@pytest.mark.django_db
def test_login_wrong_password_and_unknown_user_same_message(client):
    _make_user(username="kim", password="Abcdef1!")
    r_wrong = client.post("/accounts/login/submit/", {"username": "kim", "password": "WRONG"})
    r_unknown = client.post("/accounts/login/submit/", {"username": "nobody", "password": "x"})
    assert r_wrong.status_code == 400
    assert r_unknown.status_code == 400
    # 계정 열거(enumeration) 방지: 두 경우 동일 메시지여야 함
    assert r_wrong.json()["message"] == r_unknown.json()["message"]


# ---------- Phase 3: 마이페이지 카운트가 current_status 기반 DB 집계 ----------

@pytest.mark.django_db
def test_mypage_counts_use_current_status(client):
    from common.models_mongo import Complaints
    user = _make_user(username="kim")
    uid = user.id
    Complaints(com_id=1, user_id=uid, username="kim", com_type="청소요청", current_status="처리중").save()
    Complaints(com_id=2, user_id=uid, username="kim", com_type="수리요청", current_status="처리완료").save()
    Complaints(com_id=3, user_id=uid, username="kim", com_type="기타", current_status="처리완료").save()
    client.force_login(user)
    r = client.get("/accounts/mypage_home/")
    assert r.status_code == 200
    assert r.context["total_count"] == 3
    assert r.context["complete_count"] == 2
    assert r.context["processing_count"] == 1
