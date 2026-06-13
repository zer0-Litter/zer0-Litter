"""chatbot_core 순수 함수 + services(영속화) 테스트."""
from datetime import datetime

from chatbot import chatbot_core as core
from chatbot import services


def test_haversine_zero_distance():
    assert core.haversine(37.5, 127.0, 37.5, 127.0) == 0


def test_haversine_known_distance():
    # 위도 0.01도 차이 ≈ 약 1.11km
    d = core.haversine(37.5, 127.0, 37.51, 127.0)
    assert 1100 < d < 1120


def test_extract_complaint_types_multiple():
    result = core.extract_complaint_types("청소요청,기타 로 접수하겠습니다")
    assert set(result) == {"청소요청", "기타"}


def test_extract_complaint_types_none():
    assert core.extract_complaint_types("안녕하세요 무엇을 도와드릴까요") == []


def test_extract_complaint_types_only_known():
    assert core.extract_complaint_types("수리요청") == ["수리요청"]


def test_is_greeting_true():
    assert core.is_greeting("안녕하세요 반갑습니다")
    assert core.is_greeting("hello")


def test_is_greeting_false():
    assert not core.is_greeting("쓰레기통 어디 있어")


def test_truncate_to_full_sentence():
    assert core.truncate_to_full_sentence("첫문장. 둘째문장! 잘린문장") == "첫문장. 둘째문장!"


def test_lazy_objects_not_initialized_on_import():
    # import 시점에 LLM/Okt/벡터스토어가 생성되지 않아야 한다(테스트 가능성 보장)
    assert core._llm is None
    assert core._okt is None
    assert core._vector_store is None


# ---------- services.create_complaint_from_chat (서비스 계층 분리 성과) ----------

def _save_user_location_msg(session_id, lat=37.5, lon=127.0):
    from common.models_mongo import ChatHistory
    return ChatHistory(
        chat_id=services.get_next_chat_id(), username="u", scenario_id="complain_submit",
        session_id=session_id, role="user", content="쓰레기가 많아요",
        latitude=lat, longitude=lon, created_at=datetime.now(),
    ).save()


def test_create_complaint_skips_when_not_final():
    from common.models_mongo import Complaints
    assert services.create_complaint_from_chat("u", "s1", "서울특별시 중구", {"is_final": False}) is None
    assert Complaints.objects.count() == 0


def test_create_complaint_returns_message_when_no_location():
    from common.models_mongo import Complaints
    result = {"is_final": True, "com_type": ["청소요청"], "summary": "요약"}
    msg = services.create_complaint_from_chat("u", "s2", "서울특별시 중구", result)
    assert msg == services.NO_LOCATION_MESSAGE
    assert Complaints.objects.count() == 0


def test_create_complaint_success(monkeypatch):
    from common.models_mongo import Complaints

    # 임베딩 단계의 외부 의존(OpenAI/ChromaDB) 회피
    class _FakeVS:
        def add_documents(self, docs):
            pass

    monkeypatch.setattr(services, "get_vector_store", lambda: _FakeVS())
    _save_user_location_msg("s3", 37.5, 127.0)

    result = {"is_final": True, "com_type": ["청소요청", "기타"], "summary": "쓰레기 민원 요약"}
    msg = services.create_complaint_from_chat("u", "s3", "서울특별시 중구", result, user_id=42)

    assert msg is None
    assert Complaints.objects.count() == 1
    c = Complaints.objects.first()
    assert c.com_id >= services.CHATBOT_COM_ID_BASE  # 챗봇 민원 ID 공간
    assert c.user_id == 42  # 안정 식별자 저장
    assert c.com_type == "청소요청, 기타"
    assert c.com_location == "서울특별시 중구"
    assert c.current_status == "처리중"
    assert c.lat == 37.5 and c.lon == 127.0
