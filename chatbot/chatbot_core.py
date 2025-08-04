import uuid
import re
import os
import json
from datetime import datetime, timezone
from urllib import request

from django.template.loaders import cached
from pymongo import MongoClient, ReturnDocument
from dotenv import load_dotenv
from langchain.chat_models import ChatOpenAI
from langchain.chains import LLMChain
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from common.models import Users, TrashLoc
from common.models_mongo import Complaints, ChatHistory, ChatFiles


# --- 환경 변수 및 MongoDB 세팅 ---
load_dotenv(os.path.expanduser("~/Users/tasha/Projects/zer0-litter/.env"))
MONGO_URI = os.getenv("MONGO_URI")
print("[DEBUG] MONGO_URI:", MONGO_URI)

client = MongoClient(MONGO_URI)
print("[DEBUG] MongoDB 연결됨, DB 목록:", client.list_database_names())

# complaints_db 데이터베이스 내 컬렉션들 참조
db = client['complaints_db']
COLLECTIONS = {
    "history": db['chat_history'],       # 채팅 히스토리 저장 컬렉션
    "files": db['chat_files'],           # 채팅 관련 파일 저장 컬렉션
    "complaints": db['complaints']       # 민원 접수 정보 저장 컬렉션
}
print("[DEBUG] DB 컬렉션 접근 테스트:", COLLECTIONS["history"].find_one())


# --- LangChain LLM 세팅 ---
llm = ChatOpenAI(
    model_name="gpt-3.5-turbo",   # 사용할 OpenAI 모델명
    temperature=0.7,               # 생성 텍스트 다양성 조절값
    max_tokens=150,                # 최대 토큰 길이 제한
    streaming=False                # 스트리밍 모드 비활성화
)

# --- 문장 단위로 자르기 함수 ---
def truncate_to_full_sentence(text):
    """
    텍스트를 문장 단위로 자르고, 문장 전체를 반환
    """
    sentences = re.findall(r'.+?[.!?](?:\s|$)', text)
    return ''.join(sentences).strip()


# --- 프롬프트 템플릿 설정 ---
trash_prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template("당신은 쓰레기통 위치 안내 챗봇입니다."),
    HumanMessagePromptTemplate.from_template("사용자 질문: {user_input}")
])
trash_chain = LLMChain(llm=llm, prompt=trash_prompt)

complain_prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(
        "당신은 간결하고 효율적인 민원 접수 챗봇 AI 오엘입니다. "
        "간단한 인사말에는 대답하세요. "
        "사용자의 신고 내용을 바탕으로 누락된 정보를 확인하고, 최대한 짧고 구체적으로 질문하세요. "
        "중복된 말이나 불필요한 말은 하지 마세요."
    ),
    HumanMessagePromptTemplate.from_template("사용자 입력: {user_input}\n챗봇 질문:")
])
complain_chain = LLMChain(llm=llm, prompt=complain_prompt)


# 인사말 패턴 리스트
GREETINGS = ["안녕하세요", "안녕", "hi", "hello", "반갑습니다", "안녕하십니까"]

def is_greeting(text):
    """
    텍스트 내 인사말 여부 판단
    """
    return any(greet in text.lower() for greet in GREETINGS)


def classify_scenario(user_input):
    """
    사용자 입력에 기반해 시나리오 분류
    - complain_submit : 민원 관련 단어 포함 시
    - trash_finder : 쓰레기통 위치 관련 단어 포함 시
    - unknown : 그 외
    """
    if any(word in user_input for word in ["쓰레기", "청소", "신고", "넘침", "민원"]):
        return "complain_submit"
    if any(word in user_input for word in ["쓰레기통", "어디", "위치", "찾아줘"]):
        return "trash_finder"
    if any(word in user_input for word in ["된", "끝", "접수됐", "완료"]):
        return "complain_submit"
    return "unknown"


def analyze_metadata(user_input):
    """
    사용자 입력 분석 후 메타데이터 생성 (의도 및 엔티티 분류)
    """
    intent = "unknown_intent"
    if any(w in user_input for w in ["쓰레기", "청소", "신고", "넘침", "민원", "제보"]):
        intent = "submit_complaint"
    elif any(w in user_input for w in ["쓰레기통", "어디", "찾아줘", "위치", "현위치", "장소", "남은", "거리"]):
        intent = "find_trash_can"

    entity = "unknown_entity"
    if "쓰레기통" in user_input:
        entity = "쓰레기통"
    elif any(w in user_input for w in ["청소", "신고"]):
        entity = "민원"

    return {
        "intent": intent,
        "entity": entity,
        "confidence": 0.9
    }


from uuid import uuid4

def save_chat_history(username, scenario_id, session_id, role, content, location=None, metadata=None, is_final=False, chat_id=None):
    """
    MongoDB에 채팅 히스토리 저장
    - location: {"lat": float, "lon": float} 형식으로 받음
    - chat_id: 세션별 고유 ID 또는 메시지 연결 ID
    """
    # 고유 chat_id 생성 또는 기존 사용
    if not chat_id:
        chat_id = str(uuid4())

    lat = location.get("lat") if location else None
    lon = location.get("lon") if location else None

    doc = {
        "chat_id": chat_id,
        "username": username,
        "scenario_id": scenario_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "created_at": datetime.now(timezone.utc),
        "is_final": is_final,
        "location": {
            "lat": lat,
            "lon": lon
        },
        "metadata": metadata if metadata else {}
    }

    print(f"[DEBUG] 채팅 저장 | username={username}, scenario_id={scenario_id}, role={role}")
    print("[DEBUG] 저장 내용:", doc)

    try:
        result = COLLECTIONS["history"].insert_one(doc)
        print(f"[DEBUG] MongoDB 저장 성공: inserted_id={result.inserted_id}")
        return result.inserted_id
    except Exception as e:
        print(f"[ERROR] MongoDB 저장 실패: {e}")
        return None


def save_complaint(username, complaint_data):
    """
    MongoDB에 민원 접수 데이터 저장
    """
    complaint_data["username"] = username
    complaint_data["com_reg_date"] = datetime.now(timezone.utc)
    print("[DEBUG] 민원 저장 내용:", complaint_data)
    return COLLECTIONS["complaints"].insert_one(complaint_data).inserted_id


REQUIRED_FIELDS = ["com_location", "com_type", "com_contents"]


def infer_com_type_with_llm(user_input):
    """
    LLM을 사용해 com_type을 4가지 카테고리 중 하나로 분류
    """
    prompt = ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(
            "너는 민원 접수 도우미야. 사용자의 민원 내용을 바탕으로 com_type을 아래 4개 중 하나로 정확히 분류해.\n\n"
            "- 청소요청: 더럽다, 쓰레기가 많다 등 청소가 필요한 경우\n"
            "- 수리요청: 파손, 고장, 부서짐 등 시설 수리 관련 요청\n"
            "- 추가 요청: 쓰레기통이 부족하거나 추가 설치 요청\n"
            "- 기타민원: 위 세 가지에 포함되지 않는 불편사항\n\n"
            "반드시 네 개 중 하나를 딱 한 단어로만 출력해. 설명이나 이유 없이."
        ),
        HumanMessagePromptTemplate.from_template("{text}")
    ])
    chain = LLMChain(llm=llm, prompt=prompt)
    raw = chain.run({"text": user_input})
    result = truncate_to_full_sentence(raw)
    return result.strip()


REQUIRED_FIELDS = ["com_location", "com_type", "com_contents"]

def extract_fields(user_input, user_location=None):
    """
    사용자 입력에서 필요한 필드 추출.
    - com_location: user_location 딕셔너리 {"lat": float, "lon": float} 받아서 저장
    - com_type: LLM으로 분류 (필수)
    - 쓰레기 타입, 사진 등은 필수가 아님 -> 캐시에 저장 안함
    """
    # 안내 메시지일 경우 스킵
    if "다음 정보가 필요합니다" in user_input or "※ 민원 신고" in user_input:
        return {}

    data = {}

    # user_location이 주어지면 com_location으로 저장
    if user_location and "lat" in user_location and "lon" in user_location:
        data["com_location"] = {
            "lat": user_location["lat"],
            "lon": user_location["lon"],
            "address": user_location.get("address", "")
        }

    # com_type 추출
    com_type = infer_com_type_with_llm(user_input).replace(" ", "")
    if com_type in ["청소요청", "수리요청", "추가요청", "기타민원"]:
        data["com_type"] = [com_type]

    return data


def is_complete(complaint_data):
    """
    민원 완료 여부 판단:
    - com_type 존재해야 함 (리스트)
    - com_location 존재하고 lat, lon 모두 있어야 함
    - com_contents 존재해야 함
    """
    if not complaint_data:
        return False
    if "com_type" not in complaint_data or not complaint_data["com_type"]:
        return False
    if "com_location" not in complaint_data:
        return False
    loc = complaint_data.get("com_location")
    if not loc or "lat" not in loc or "lon" not in loc:
        return False
    if "com_contents" not in complaint_data or not complaint_data["com_contents"]:
        return False
    return True


def is_checking_completion(user_input):
    """
    사용자가 민원 완료 여부를 확인하는 의도인지 판단
    """
    return any(kw in user_input for kw in ["된", "끝", "완료", "접수됐", "끝난"])


complaint_cache = {}


def handle_complain_submit(user_input, prev_messages, username, session_id="default-session", user_location=None):
    """
    민원 접수 처리 함수
    """
    session_key = f"{username}_{session_id}"
    cached = complaint_cache.get(session_key, {})

    extracted = extract_fields(user_input, user_location=user_location)
    cached.update(extracted)
    cached["com_contents"] = user_input

    if is_checking_completion(user_input):
        if is_complete(cached):
            return "신고는 이미 완료된 상태입니다."
        else:
            missing = [f for f in REQUIRED_FIELDS if f not in cached or not cached[f]]
            return f"아직 신고가 완료되지 않았습니다. 필요한 정보: {', '.join(missing)}"

    prompt_text = complain_prompt.format_prompt(user_input=user_input).to_string()
    response = complain_chain.run({"user_input": user_input})
    response = truncate_to_full_sentence(response)

    response_status = "complete" if is_complete(cached) else "partial"
    meta = {
        "prompt": prompt_text,
        "llm_response": response,
        "response_status": response_status,
        "required_fields_filled": is_complete(cached),
        "missing_fields": [f for f in REQUIRED_FIELDS if f not in cached or not cached[f]]
    }

    if is_complete(cached):
        final_data = {
            **cached,
            "re_complain": "Y",
            "status_id": 1,
            "com_title": cached.get("com_title", "사용자 신고"),
            "com_pic2": None,
            "username": username,
            "com_reg_date": datetime.now(timezone.utc)
        }
        save_complaint(username, final_data)
        complaint_cache.pop(session_key, None)
        response += "\n신고가 접수되었습니다. 빠르게 처리하겠습니다."
    else:
        missing = meta["missing_fields"]
        response += f"\n\n추가로 다음 정보가 필요합니다: {', '.join(missing)}"

    complaint_cache[session_key] = cached
    save_chat_history(username, "complain_submit", session_id, "bot", response, metadata=meta, is_final=is_complete(cached), location=user_location)

    return response



def handle_trash_finder(user_input, prev_messages):
    """
    쓰레기통 위치 안내 처리 함수
    """
    response = trash_chain.run({"user_input": user_input})
    response = truncate_to_full_sentence(response)
    return response


def generate_session_id():
    """
    세션 ID 생성 (UUID 기반 8자리 hex)
    """
    return f"session-{uuid.uuid4().hex[:8]}"


def generate_chat_id():
    """
    채팅 ID 자동증가 생성기
    MongoDB counters 컬렉션에 seq 필드 1씩 증가시켜 관리
    """
    counter = db.counters.find_one_and_update(
        {'_id': 'chat_id'},
        {'$inc': {'seq': 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    return counter['seq']


def validate_user_location(request):
    """
    POST 요청에서 위도(lat), 경도(lon) 값을 추출 및 검증
    - 올바르지 않으면 ValueError 발생
    """
    lat = request.POST.get('lat')
    lon = request.POST.get('lon')
    if not lat or not lon:
        raise ValueError("민원 위치 정보가 필요합니다. 지도를 눌러 현위치를 알려주세요.")
    try:
        return {"lat": float(lat), "lon": float(lon)}
    except ValueError:
        raise ValueError("위도, 경도 값이 올바르지 않습니다.")


def load_chat_history(username, scenario_id, limit=5):
    """
    MongoDB에서 최근 채팅 히스토리 로드 (최대 limit개)
    """
    cursor = COLLECTIONS["history"].find({
        "username": username,
        "scenario_id": scenario_id
    }).sort("created_at", -1).limit(limit)
    # 오래된 순서대로 정렬 후 반환
    return list(cursor)[::-1]


def chatbot_router(user_input, username, session_id=None, scenario_id=None, user_location=None):
    """
    메인 챗봇 라우터 함수
    - 사용자 입력 및 상태에 따라 시나리오 분기
    - 인사말, 쓰레기통 위치 안내, 민원 접수 처리
    - 모든 채팅 기록은 MongoDB에 저장 (위치정보 포함)
    """
    print(f"[DEBUG] chatbot_router 진입 | username={username}, message='{user_input}'")

    # 사용자 존재 여부 확인 (Django ORM)
    try:
        Users.objects.get(username=username)
    except Users.DoesNotExist:
        print("[ERROR] 사용자 없음:", username)
        return "사용자 정보를 찾을 수 없습니다."

    # session_id 없으면 생성
    if session_id is None:
        session_id = generate_session_id()

    # 유저 메시지를 먼저 저장해야 로그가 자연스럽게 보입니다.
    save_chat_history(username, "greeting", session_id, "user", user_input, location=user_location)

    # 인사말 판단 및 처리
    if is_greeting(user_input):
        greeting_response = (
            "안녕하세요. AI 오엘입니다. 무엇을 도와드릴까요?\n"
            "아래의 버튼 중 도움이 필요한 부분을 선택해 주세요."
        )
        save_chat_history(username, "greeting", session_id, "bot", greeting_response, location=user_location)
        return greeting_response

    # 시나리오 분류
    if scenario_id is None:
        scenario_id = classify_scenario(user_input)

    if scenario_id == "unknown":
        unknown_response = "해당 질문은 지원하지 않습니다."
        save_chat_history(username, "unknown", session_id, "user", user_input, location=user_location)
        save_chat_history(username, "unknown", session_id, "bot", unknown_response, location=user_location)
        return unknown_response

    # 이전 메시지 불러오기
    prev_messages = load_chat_history(username, scenario_id)

    # 시나리오별 처리
    if scenario_id == 'trash_finder':
        response = handle_trash_finder(user_input, prev_messages)
    elif scenario_id == 'complain_submit':
        response = handle_complain_submit(user_input, prev_messages, username, session_id, user_location)
        session_key = f"{username}_{session_id}"
        cached = complaint_cache.get(session_key, {})
        if not is_complete(cached):
            response += "\n\n※ 민원 신고를 완료하시려면 필요한 정보를 모두 입력해 주세요."
    else:
        response = "해당 질문은 지원하지 않습니다."

    # 유저 위치 파싱 (이미 존재할 가능성 높음)
    user_location = request.POST.get('location')
    if user_location:
        user_location = json.loads(user_location)

    # 사용자 및 봇 대화 저장 (위치 포함)
    save_chat_history(username, scenario_id, session_id, "user", user_input, location=user_location)
    save_chat_history(
        username,
        scenario_id,
        session_id,
        "bot",
        response,
        is_final=is_complete(complaint_cache.get(f"{username}_{session_id}", {})),
        location=user_location
    )

    return response
