import uuid
from datetime import datetime, timezone
from pymongo import MongoClient
from dotenv import load_dotenv
from langchain.chat_models import ChatOpenAI
from langchain.chains import LLMChain
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
import os
import re
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from common.models import Users, TrashLoc
from common.models_mongo import Complaints, ChatHistory, ChatFiles
import json


# --- 환경 변수 및 MongoDB 세팅 ---
load_dotenv(os.path.expanduser("~/Users/tasha/Projects/zer0-litter/.env"))
MONGO_URI = os.getenv("MONGO_URI")
print("[DEBUG] MONGO_URI:", MONGO_URI)
client = MongoClient(MONGO_URI)
print("[DEBUG] MongoDB 연결됨, DB 목록:", client.list_database_names())

db = client['complaints_db']
COLLECTIONS = {
    "history": db['chat_history'],       # 채팅 히스토리 저장 컬렉션
    "files": db['chat_files'],           # 채팅 관련 파일 저장 컬렉션
    "complaints": db['complaints']       # 민원 접수 정보 저장 컬렉션
}
# 디버깅용
print("[DEBUG] DB 컬렉션 접근 테스트:", COLLECTIONS["history"].find_one())



# --- LangChain LLM 세팅 ---
llm = ChatOpenAI(
    model_name="gpt-3.5-turbo",  # 사용할 OpenAI 모델명
    temperature=0.7,              # 생성 텍스트 다양성 조절값
    max_tokens=150,               # 최대 토큰 길이
    streaming=False               # 스트리밍 모드 비활성화
)

# --- 문장 단위로 자르기 ---
def truncate_to_full_sentence(text):
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

GREETINGS = ["안녕하세요", "안녕", "hi", "hello", "반갑습니다", "안녕하십니까"]

def is_greeting(text):
    return any(greet in text.lower() for greet in GREETINGS)

def classify_scenario(user_input):
    if any(word in user_input for word in ["쓰레기", "청소", "신고", "넘침", "민원"]):
        return "complain_submit"
    if any(word in user_input for word in ["쓰레기통", "어디", "위치", "찾아줘"]):
        return "trash_finder"
    if any(word in user_input for word in ["된", "끝", "접수됐", "완료"]):
        return "complain_submit"
    return "unknown"

def analyze_metadata(user_input):
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

def save_chat_history(user_id, scenario_id, session_id, role, content, location=None, metadata=None, is_final=False):
    doc = {
        "user_id": user_id,  # 여기 user_id는 실제 username임
        "scenario_id": scenario_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "created_at": datetime.now(timezone.utc),
        "is_final": is_final,
        "location": location if location else {},
        "metadata": metadata if metadata else {}
    }
    print(f"[DEBUG] 채팅 저장 | user_id={user_id}, scenario_id={scenario_id}, role={role}")
    print("[DEBUG] 저장 내용:", doc)
    return COLLECTIONS["history"].insert_one(doc).inserted_id

def save_complaint(user_id, complaint_data):
    complaint_data["user_id"] = user_id  # username 저장
    complaint_data["com_reg_date"] = datetime.now(timezone.utc)
    print("[DEBUG] 민원 저장 내용:", complaint_data)
    return COLLECTIONS["complaints"].insert_one(complaint_data).inserted_id

REQUIRED_FIELDS = ["com_location", "com_type", "com_contents"]

# -- com_type 자동 분류 (4개 중 하나로 제한)
def infer_com_type_with_llm(user_input):
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


def extract_fields(user_input):
    # 안내 메시지일 경우 추출 스킵
    if "다음 정보가 필요합니다" in user_input or "※ 민원 신고" in user_input:
        return {}

    data = {}

    if "강남" in user_input:
        data["com_location"] = "서울시 강남구"
        #data["t_district_id"] = "GN01"

    com_type = infer_com_type_with_llm(user_input).replace(" ", "")
    if com_type in ["청소요청", "수리요청", "추가요청", "기타민원"]:
        data["com_type"] = [com_type]

    if "쓰레기" in user_input:
        data["com_trash_type"] = "일반쓰레기"
        data["com_trashcan"] = "O"

    if any(x in user_input for x in ["사진", "첨부", "이미지"]):
        data["com_pic1"] = "dummy_pic_url"

    return data



def is_complete(complaint_data):
    return all(k in complaint_data and complaint_data[k] for k in REQUIRED_FIELDS)

def is_checking_completion(user_input):
    return any(kw in user_input for kw in ["된", "끝", "완료", "접수됐", "끝난"])

complaint_cache = {}

def handle_complain_submit(user_input, prev_messages, user_id, session_id="default-session"):
    session_key = f"{user_id}_{session_id}"
    cached = complaint_cache.get(session_key, {})

    extracted = extract_fields(user_input)
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
            "user_id": user_id,
            "com_reg_date": datetime.now(timezone.utc)
        }
        save_complaint(user_id, final_data)
        complaint_cache.pop(session_key, None)
        response += "\n신고가 접수되었습니다. 빠르게 처리하겠습니다."
    else:
        missing = meta["missing_fields"]
        response += f"\n\n추가로 다음 정보가 필요합니다: {', '.join(missing)}"

    complaint_cache[session_key] = cached
    save_chat_history(user_id, "complain_submit", session_id, "bot", response, metadata=meta, is_final=is_complete(cached))

    return response

def handle_trash_finder(user_input, prev_messages):
    response = trash_chain.run({"user_input": user_input})
    response = truncate_to_full_sentence(response)
    return response

def generate_session_id():
    return f"session-{uuid.uuid4().hex[:8]}"

def load_chat_history(user_id, scenario_id, limit=5):
    cursor = COLLECTIONS["history"].find({
        "user_id": user_id,
        "scenario_id": scenario_id
    }).sort("created_at", -1).limit(limit)
    return list(cursor)[::-1]

def chatbot_router(user_input, user_id, session_id=None, scenario_id=None, user_location=None):
    # user_id는 실제 username 값임

    # 사용자 존재 여부 체크 (username 기준)
    print(f"[DEBUG] chatbot_router 진입 | user_id={user_id}, message='{user_input}'")

    try:
        Users.objects.get(username=user_id)
    except Users.DoesNotExist:
        print("[ERROR] 사용자 없음:", user_id)
        return "사용자 정보를 찾을 수 없습니다."

    if session_id is None:
        session_id = generate_session_id()

    if is_greeting(user_input):
        greeting_response = (
            "안녕하세요. AI 오엘입니다. 무엇을 도와드릴까요?\n"
            "아래 버튼 중 도움이 필요한 부분을 선택해 주세요."
        )
        save_chat_history(user_id, "greeting", session_id, "user", user_input, location=user_location)
        save_chat_history(user_id, "greeting", session_id, "bot", greeting_response)
        return greeting_response

    if scenario_id is None:
        scenario_id = classify_scenario(user_input)

    if scenario_id == "unknown":
        unknown_response = "해당 질문은 지원하지 않습니다."
        save_chat_history(user_id, "unknown", session_id, "user", user_input, location=user_location)
        save_chat_history(user_id, "unknown", session_id, "bot", unknown_response)
        return unknown_response

    prev_messages = load_chat_history(user_id, scenario_id)

    if scenario_id == 'trash_finder':
        response = handle_trash_finder(user_input, prev_messages)
    elif scenario_id == 'complain_submit':
        response = handle_complain_submit(user_input, prev_messages, user_id, session_id)
        session_key = f"{user_id}_{session_id}"
        cached = complaint_cache.get(session_key, {})
        if not is_complete(cached):
            response += "\n\n※ 민원 신고를 완료하시려면 필요한 정보를 모두 입력해 주세요."
    else:
        response = "해당 질문은 지원하지 않습니다."

    save_chat_history(user_id, scenario_id, session_id, "user", user_input, location=user_location)
    save_chat_history(
        user_id,
        scenario_id,
        session_id,
        "bot",
        response,
        is_final=is_complete(complaint_cache.get(f"{user_id}_{session_id}", {}))
    )

    return response

