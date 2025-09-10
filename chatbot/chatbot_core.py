import os, re
from datetime import datetime, timezone
import time
from pymongo import MongoClient, ReturnDocument
from dotenv import load_dotenv
from langchain.chat_models import ChatOpenAI
from langchain.chains import LLMChain
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from config import settings

MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client['complaints_db']
COLLECTIONS = {
    "history": db['chat_history'],
    "files": db['chat_files'],
    "complaints": db['complaints']
}

# --- LLM 세팅 ---
# 💡 모델 이름을 gpt-4o-mini로 변경했습니다.
llm = ChatOpenAI(model_name="gpt-4o-mini", temperature=0.7, max_tokens=150, api_key=settings.OPENAI_API_KEY)

# --- 프롬프트 ---
trash_prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template("당신은 쓰레기통 위치 안내 챗봇입니다."),
    HumanMessagePromptTemplate.from_template("사용자 질문: {user_input}")
])
trash_chain = LLMChain(llm=llm, prompt=trash_prompt)

# --- com_type 분류를 위한 프롬프트(전역 재사용) ---
_com_type_prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(
        "다음 대화를 참고하여 사용자가 제기한 민원을 "
        "'청소요청', '수리요청', '추가요청', '기타민원' 중 하나로 분류하세요. "
        "가능한 경우 유형만 정확히 반환하세요. 모를 경우 가장 가능성 높은 항목 하나를 제안하세요."
    ),
    HumanMessagePromptTemplate.from_template("대화 내용:\n{context}\n\n최신 발화: {text}")
])
com_type_chain = LLMChain(llm=llm, prompt=_com_type_prompt)

# 💡 자연스러운 후속 질문을 위한 새로운 LLM 프롬프트
_follow_up_prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(
        "당신은 친절한 민원 접수 챗봇입니다. 사용자의 민원을 정확히 접수하기 위해 추가 정보를 요청해야 합니다."
        "사용자가 '쓰레기'에 대해 말했으나, 구체적인 민원 유형('청소요청', '수리요청', '추가요청', '기타민원')을 명시하지 않았습니다."
        "다음 규칙에 따라 자연스러운 질문을 하나만 생성하세요:"
        "1. 질문은 '쓰레기통'이라는 단어를 포함해야 합니다."
        "2. 사용자가 어떤 종류의 민원을 제기하는지 ('청소', '수리', '추가' 등)를 명확하게 추론할 수 있도록 유도하는 질문이어야 합니다."
        "3. 예시: '쓰레기통이 고장 났나요, 아니면 청소가 필요한가요?' 또는 '쓰레기통을 추가로 설치해 드릴까요?'"
    ),
    HumanMessagePromptTemplate.from_template("사용자 발화: {user_input}")
])
follow_up_chain = LLMChain(llm=llm, prompt=_follow_up_prompt)

GREETINGS = ["안녕하세요", "안녕", "hi", "hello", "반갑습니다", "안녕하십니까"]


def is_greeting(text):
    return any(greet in text.lower() for greet in GREETINGS)


def classify_scenario(user_input):
    if any(word in user_input for word in ["쓰레기", "청소", "신고", "넘침", "민원"]):
        return "complain_submit"
    if any(word in user_input for word in ["쓰레기통", "어디", "위치", "찾아줘"]):
        return "trash_finder"
    return "unknown"


def truncate_to_full_sentence(text):
    sentences = re.findall(r'.+?[.!?](?:\s|$)', text)
    return ''.join(sentences).strip()


# -------------------------------
# Counter 기반 ID 생성
# -------------------------------
def generate_session_id():
    counter = db.counters.find_one_and_update(
        {'_id': 'session_id'},
        {'$inc': {'seq': 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    return f"session_{counter['seq']}"


def generate_chat_id():
    counter = db.counters.find_one_and_update(
        {'_id': 'chat_id'},
        {'$inc': {'seq': 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    return counter['seq']


# -------------------------------
# DB 저장 함수
# -------------------------------
def save_chat_history(username, scenario_id, session_id, role, content, is_final=False, metadata=None):
    record = {
        "chat_id": generate_chat_id(),
        "username": username,
        "scenario_id": scenario_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "is_final": is_final,
        "metadata": metadata or {},
        "created_at": datetime.now(timezone.utc)
    }
    COLLECTIONS["history"].insert_one(record)


def save_complaint(username, complaint_data):
    complaint_data["username"] = username
    complaint_data["com_reg_date"] = datetime.now(timezone.utc)
    return COLLECTIONS["complaints"].insert_one(complaint_data).inserted_id


# -------------------------------
# 민원 처리
# -------------------------------
REQUIRED_FIELDS = ["com_type", "lat", "lon"]
complaint_cache = {}


def infer_com_type_with_llm(user_input, chat_history=None):
    context = ""
    if chat_history:
        context = "\n".join([f"{msg['role']}: {msg['message']}" for msg in chat_history[-5:]])

    try:
        result = com_type_chain.predict(context=context, text=user_input)
    except Exception as e:
        result = ""

    if isinstance(result, dict):
        raw = result.get("text") or result.get("output") or str(result)
    else:
        raw = str(result)

    return truncate_to_full_sentence(raw).strip()


def extract_fields(user_input, chat_history=None):
    data = {}
    lowered = user_input.replace(" ", "").lower()

    if any(k in lowered for k in ["청소", "청소요청", "치우", "청소해"]):
        data["com_type"] = "청소요청"
    elif any(k in lowered for k in ["수리", "수리요청", "고장", "수선"]):
        data["com_type"] = "수리요청"
    elif any(k in lowered for k in ["추가", "추가요청", "더", "설치"]):
        data["com_type"] = "추가요청"
    elif any(k in lowered for k in ["기타", "기타민원"]):
        data["com_type"] = "기타민원"
    else:
        raw_com_type = infer_com_type_with_llm(user_input, chat_history)
        cleaned = raw_com_type.replace(" ", "")

        valid_types = ["청소요청", "수리요청", "추가요청", "기타민원"]
        for t in valid_types:
            if t in cleaned:
                data["com_type"] = t
                break
        else:
            data["com_type"] = None

    data["com_contents"] = user_input
    return data


def is_complete(complaint_data):
    if not complaint_data: return False
    return all(complaint_data.get(f) for f in REQUIRED_FIELDS)


# 💡 handle_complain_submit 함수를 완전히 재작성하여 동적으로 응답을 생성합니다.
def handle_complain_submit(user_input, username, session_id, chat_history=None):
    extracted_fields = extract_fields(user_input, chat_history)
    com_type = extracted_fields.get("com_type")

    if com_type:
        # 유형이 파악된 경우, 확정 응답 반환
        response = f"네, 민원 유형이 {com_type}으로 확인되었습니다. 더 자세한 내용을 말씀해주시면 접수해 드릴게요."
    else:
        # 유형이 파악되지 않은 경우, 자연스러운 후속 질문을 LLM에게 요청
        try:
            response = follow_up_chain.predict(user_input=user_input)
            response = truncate_to_full_sentence(response)
        except Exception as e:
            # LLM 호출 실패 시, 기존의 대놓고 묻는 응답으로 폴백
            logger.error(f"Follow-up question generation failed: {e}", exc_info=True)
            response = "쓰레기와 관련된 민원으로 보입니다. 어떤 유형인가요? (청소요청, 수리요청, 추가요청, 기타민원)"

    return {"response": response, "com_type": com_type}


def handle_trash_finder(user_input, username, session_id):
    response = trash_chain.run({"user_input": user_input})
    final_response = truncate_to_full_sentence(response)

    return {"response": final_response}


def chatbot_router(user_input, username, session_id=None, scenario_id=None):
    start_time = time.time()

    if session_id is None:
        session_id = generate_session_id()
    if scenario_id is None:
        scenario_id = classify_scenario(user_input)

    if is_greeting(user_input):
        response = "안녕하세요! 무엇을 도와드릴까요?"
        return {"response": response, "session_id": session_id}

    if scenario_id == "complain_submit":
        result = handle_complain_submit(user_input, username, session_id)
        result["session_id"] = session_id
        return result
    elif scenario_id == "trash_finder":
        result = handle_trash_finder(user_input, username, session_id)
        result["session_id"] = session_id
        return result
    else:
        response = "지원하지 않는 질문입니다."
        return {"response": response, "session_id": session_id}