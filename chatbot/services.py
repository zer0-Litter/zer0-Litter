"""챗봇 영속화/비즈니스 로직.

chatbot_api 뷰에 섞여 있던 ID 발급 · ChromaDB 초기화 · 메시지/파일/민원 저장 로직을
HTTP 와 분리해 한곳에 모은 서비스 계층. 뷰는 요청 파싱과 응답에만 집중하고,
여기 함수들은 mongomock 으로 단위 테스트가 가능하다.
"""
import logging
from datetime import datetime
from uuid import uuid4

from langchain.docstore.document import Document as LangchainDocument

from common.models_mongo import ChatHistory, Counter, ChatFiles, Complaints
from chatbot.chatbot_core import get_vector_store

logger = logging.getLogger(__name__)

# 챗봇 민원과 일반 민원을 com_id 범위로 구분: 챗봇 민원은 1000000번대 사용
CHATBOT_COM_ID_BASE = 1000000


# ===================== ID 발급 =====================

def get_next_chatbot_com_id():
    """챗봇 민원 ID를 Counter로 원자적으로 발급(1000000번대 보장, 동시성 중복키 방지)."""
    c = Counter.objects(name='chatbot_complaint').first()
    if not c or (c.seq or 0) < CHATBOT_COM_ID_BASE:
        # 최초 1회 시드: 이미 1000000번대 챗봇 민원이 존재할 수 있으므로 실제 최댓값에서 이어간다.
        latest = (Complaints.objects(com_id__gte=CHATBOT_COM_ID_BASE)
                  .order_by('-com_id').first())
        seed = latest.com_id if (latest and isinstance(latest.com_id, int)) else CHATBOT_COM_ID_BASE
        Counter.objects(name='chatbot_complaint').update_one(upsert=True, set__seq=seed)
    return Counter.objects(name='chatbot_complaint').modify(upsert=True, new=True, inc__seq=1).seq


def _next_prefixed_id(counter_name, prefix):
    """Counter 기반 '<prefix>_<seq>' ID 발급. 실패 시 UUID 폴백."""
    try:
        counter = Counter.objects(name=counter_name).modify(upsert=True, new=True, inc__seq=1)
        if not counter:
            counter = Counter(name=counter_name, seq=1)
            counter.save()
        return f"{prefix}_{counter.seq}"
    except Exception as e:
        logger.error("%s 생성 실패: %s", counter_name, e)
        return f"{prefix}_{uuid4()}"


def get_next_chat_id():
    return _next_prefixed_id('chat_id', 'chat')


def get_next_session_id():
    return _next_prefixed_id('session_id', 'session')


def get_next_file_id():
    return _next_prefixed_id('file_id', 'file')


# ===================== ChromaDB 초기 로드 =====================

_chroma_initialized = False


def initial_load_to_chroma():
    """ChromaDB가 비어 있을 때만 MongoDB의 기존 민원을 임베딩해 로드한다."""
    try:
        vector_store = get_vector_store()
        if vector_store._collection.count() == 0:
            logger.info("ChromaDB가 비어 있습니다. MongoDB에서 기존 민원 데이터를 로드합니다...")
            documents = []
            for complaint in Complaints.objects():
                com_type_value = complaint.com_type
                if isinstance(com_type_value, list) and com_type_value:
                    com_type_value = com_type_value[0]
                documents.append(LangchainDocument(
                    page_content=complaint.com_contents,
                    metadata={
                        "username": complaint.username,
                        "com_id": complaint.com_id,
                        "com_type": com_type_value,
                    },
                ))
            if documents:
                vector_store.add_documents(documents)
                logger.info("MongoDB에서 총 %d개의 민원 데이터를 ChromaDB에 로드 완료.", len(documents))
        else:
            logger.info("ChromaDB에 이미 데이터가 존재하여 초기 로드를 건너뜁니다.")
    except Exception as e:
        logger.error("ChromaDB 초기 로드 실패: %s", e, exc_info=True)


def ensure_chroma_loaded():
    """import 시점 과금/조회를 피해 첫 요청 때 1회만 초기 로드한다."""
    global _chroma_initialized
    if _chroma_initialized:
        return
    _chroma_initialized = True
    initial_load_to_chroma()


# ===================== 메시지/파일 저장 =====================

def save_user_message(username, scenario_id, session_id, content, lat, lon):
    """사용자 메시지를 ChatHistory에 저장하고 문서를 반환(실패 시 None)."""
    try:
        chat_doc = ChatHistory(
            chat_id=get_next_chat_id(),
            username=username,
            scenario_id=scenario_id,
            session_id=session_id,
            role='user',
            content=content,
            latitude=lat,
            longitude=lon,
            is_final=False,
            metadata={},
            created_at=datetime.now(),
        )
        chat_doc.save()
        logger.debug("ChatHistory 저장 완료(user): %s", chat_doc.chat_id)
        return chat_doc
    except Exception as e:
        logger.error("ChatHistory(user) 저장 실패: %s", e, exc_info=True)
        return None


def save_uploaded_files(chat_doc, files):
    """업로드 파일들을 ChatFiles에 저장(타입/용량 검증은 뷰에서 이미 수행)."""
    if not chat_doc or not files:
        return
    try:
        for f in files:
            file_id = get_next_file_id()
            f.seek(0)
            ChatFiles(
                file_id=file_id,
                chat_id=chat_doc,
                file_name=f.name,
                file_data=f.read(),
                file_type=getattr(f, "content_type", ""),
                uploaded_at=datetime.now(),
            ).save()
            logger.debug("파일 저장 완료: file_id=%s", file_id)
    except Exception as e:
        logger.error("파일 저장 처리 실패: %s", e, exc_info=True)


def save_bot_message(username, scenario_id, session_id, result):
    """챗봇 응답을 ChatHistory에 저장(추론된 com_type을 metadata에 기록)."""
    try:
        ChatHistory(
            chat_id=get_next_chat_id(),
            username=username,
            scenario_id=scenario_id,
            session_id=session_id,
            role='assistant',
            content=result.get('response', ''),
            is_final=result.get('is_final', False),
            metadata={'com_type': result.get('com_type', [])},
            created_at=datetime.now(),
        ).save()
        logger.debug("ChatHistory 저장 완료(bot)")
    except Exception as e:
        logger.error("ChatHistory(bot) 저장 실패: %s", e, exc_info=True)


# ===================== 민원 자동 생성 =====================

# 위치 정보가 부족해 민원 접수를 중단할 때 사용자에게 보여줄 메시지
NO_LOCATION_MESSAGE = (
    '죄송합니다. 위치 정보가 없어 민원 접수가 어렵습니다. 위치 정보를 포함하여 다시 시도해 주세요.'
)


def _resolve_com_location(session_id, temp_com_location):
    """민원 주소 결정: 요청값 우선, 없으면 '위치확인_주소:' 메시지에서 추출."""
    if temp_com_location:
        return temp_com_location
    location_msg_doc = (ChatHistory.objects(session_id=session_id, role='user',
                                            content__startswith='위치확인_주소:')
                        .order_by('created_at').first())
    if location_msg_doc:
        return location_msg_doc.content.replace('위치확인_주소:', '').strip()
    return ''


def create_complaint_from_chat(username, session_id, temp_com_location, result, user_id=None):
    """대화가 최종 확정(is_final)되면 민원을 생성하고 임베딩한다.

    반환:
        None                 - 정상 처리(또는 생성 대상 아님)
        NO_LOCATION_MESSAGE  - 위경도 부족으로 접수 중단(사용자 안내 필요)
    예기치 못한 오류는 호출측에서 처리하도록 예외를 전파한다.
    """
    if not result.get('is_final', False):
        return None

    com_type_from_router = result.get('com_type')
    complaint_summary = result.get('summary')

    # 위경도는 위치를 포함한 첫 사용자 메시지에서 가져온다
    location_doc = (ChatHistory.objects(session_id=session_id, role='user', latitude__exists=True)
                    .order_by('created_at').first())
    final_com_location = _resolve_com_location(session_id, temp_com_location)
    if not final_com_location:
        logger.warning("민원(session_id=%s) 주소 정보 부족", session_id)

    if not location_doc or not location_doc.latitude or not location_doc.longitude:
        logger.warning("민원(session_id=%s) 위경도 부족 → 접수 취소", session_id)
        return NO_LOCATION_MESSAGE

    if not com_type_from_router:
        return None

    complaint_id = get_next_chatbot_com_id()
    com_type_for_db = (', '.join(com_type_from_router)
                       if isinstance(com_type_from_router, list) else com_type_from_router)

    complaint_data = {
        "com_id": complaint_id,
        "user_id": user_id,
        "username": username,
        "com_type": com_type_for_db,
        "lat": location_doc.latitude,
        "lon": location_doc.longitude,
        "com_contents": complaint_summary,
        "com_reg_date": datetime.now(),
        "com_location": final_com_location,
        "current_status": "처리중",
    }

    # 해당 세션의 첨부파일을 최대 2개까지 연결
    user_msgs = ChatHistory.objects(session_id=session_id, role='user',
                                    scenario_id='complain_submit').order_by('created_at')
    related_files = (ChatFiles.objects(chat_id__in=[m.id for m in user_msgs])
                     .order_by("-uploaded_at")[:2])
    for i, f in enumerate(related_files):
        complaint_data[f"com_pic{i + 1}"] = f.file_data

    Complaints(**complaint_data).save()
    logger.info("Complaints 저장 완료: com_id=%s", complaint_id)

    # 유사검색용 임베딩 저장
    get_vector_store().add_documents([LangchainDocument(
        page_content=complaint_summary,
        metadata={"username": username, "com_id": complaint_id, "com_type": com_type_for_db},
    )])
    logger.info("ChromaDB에 임베딩 저장 완료")
    return None
