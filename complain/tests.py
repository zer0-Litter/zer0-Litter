"""complain 앱 테스트: IDOR/권한 방어 + Counter 단조 증가 (mongomock 사용)."""
import json
import pytest

from common.models_mongo import Complaints


def _make_user(username):
    from common.models import Users
    return Users.objects.create_user(
        username=username, password="Abcdef1!", name="홍길동",
        birth="1990-01-01", gender="M", address="서울특별시", phone_number="01000000000",
    )


def _make_complaint(com_id, owner=None, username="someone", current_status="처리중"):
    """owner(Users)가 주어지면 user_id/username 을 그 사용자로 설정. 없으면 username 만."""
    return Complaints(
        com_id=com_id,
        user_id=(owner.id if owner else None),
        username=(owner.username if owner else username),
        com_type="청소요청", com_contents="내용", com_location="서울특별시 중구",
        current_status=current_status,
    ).save()


def _make_staff(username):
    from common.models import Users
    u = Users.objects.create_user(
        username=username, password="Abcdef1!", name="관리자",
        birth="1990-01-01", gender="M", address="서울특별시", phone_number="01000000000",
    )
    u.is_staff = True
    u.save()
    return u


# ---------- Counter 단조 증가 ----------

@pytest.mark.django_db
def test_counter_monotonic():
    from complain.views import get_next_com_id
    a = get_next_com_id()
    b = get_next_com_id()
    assert b == a + 1


# ---------- IDOR: 재민원(complain_reuse) ----------

@pytest.mark.django_db
def test_reuse_other_users_complaint_is_404(client):
    attacker = _make_user("attacker")
    victim = _make_user("victim")
    _make_complaint(com_id=1001, owner=victim)  # 남의 민원
    client.force_login(attacker)
    r = client.get("/complain/reuse/1001/")
    assert r.status_code == 404


@pytest.mark.django_db
def test_reuse_own_complaint_is_ok(client):
    owner = _make_user("owner")
    _make_complaint(com_id=1002, owner=owner)
    client.force_login(owner)
    r = client.get("/complain/reuse/1002/")
    assert r.status_code == 200


# ---------- IDOR: 민원 수정 API ----------

@pytest.mark.django_db
def test_update_other_users_complaint_is_404(client):
    attacker = _make_user("attacker")
    victim = _make_user("victim")
    _make_complaint(com_id=2001, owner=victim)
    client.force_login(attacker)
    r = client.post(
        "/accounts/api/complaints/update/",
        data=json.dumps({"com_id": 2001, "content": "해킹시도"}),
        content_type="application/json",
    )
    assert r.status_code == 404
    # 원본 내용이 바뀌지 않았는지 확인
    assert Complaints.objects.get(com_id=2001).com_contents == "내용"


@pytest.mark.django_db
def test_update_own_complaint_succeeds(client):
    owner = _make_user("owner")
    _make_complaint(com_id=2002, owner=owner)
    client.force_login(owner)
    r = client.post(
        "/accounts/api/complaints/update/",
        data=json.dumps({"com_id": 2002, "content": "수정된 내용"}),
        content_type="application/json",
    )
    assert r.status_code == 200
    assert Complaints.objects.get(com_id=2002).com_contents == "수정된 내용"


# ---------- Phase 3: current_status 비정규화 ----------

@pytest.mark.django_db
def test_mark_completed_updates_current_status(client):
    from common.models_mongo import ComplaintStatus
    staff = _make_staff("staff")
    _make_complaint(com_id=3001, username="user", current_status="처리중")
    client.force_login(staff)
    r = client.post("/complain/manage/3001/complete/")
    assert r.status_code in (302, 200)
    # 비정규화 필드가 갱신되고, 이력도 남아야 한다
    assert Complaints.objects.get(com_id=3001).current_status == "처리완료"
    assert ComplaintStatus.objects(com_id=3001, status_name="처리완료").count() == 1


@pytest.mark.django_db
def test_staff_pending_list_filters_by_current_status(client):
    staff = _make_staff("staff")
    _make_complaint(com_id=4001, username="u", current_status="처리중")
    _make_complaint(com_id=4002, username="u", current_status="처리완료")
    client.force_login(staff)
    r = client.get("/complain/manage/pending/")
    assert r.status_code == 200
    shown_ids = {it["doc"].com_id for it in r.context["page_obj"].object_list}
    assert shown_ids == {4001}  # 처리중만


# ---------- 정합성: 계정 삭제 시 Mongo 연관 데이터 연쇄 정리 ----------

@pytest.mark.django_db
def test_account_delete_purges_related_mongo_data():
    from datetime import datetime
    from common.models_mongo import ComplaintStatus, ChatHistory

    leaver = _make_user("leaver")
    keeper = _make_user("keeper")
    _make_complaint(com_id=5001, owner=leaver)
    ComplaintStatus(status_id=9001, com_id=5001, status_name="처리중", updated_at=datetime.now()).save()
    ChatHistory(chat_id="chat_x", username="leaver", role="user",
                content="안녕", created_at=datetime.now()).save()
    _make_complaint(com_id=5002, owner=keeper)  # 타인 데이터(보존돼야 함)

    leaver.delete()  # post_delete 시그널 → Mongo 정리

    assert Complaints.objects(com_id=5001).count() == 0
    assert ComplaintStatus.objects(com_id=5001).count() == 0
    assert ChatHistory.objects(username="leaver").count() == 0
    # 다른 사용자 데이터는 그대로
    assert Complaints.objects(com_id=5002).count() == 1
