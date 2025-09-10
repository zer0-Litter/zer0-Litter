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
    "files": db['chat_files'],  # 발화별 저장
    "complaints": db['complaints']
}

# --- LLM 세팅 ---
# (성능 위해 전역 llm 하나만 사용. 필요시 max_tokens, timeout 조정 가능)
llm = ChatOpenAI(model_name="gpt-3.5-turbo", temperature=0.7, max_tokens=150, api_key=settings.OPENAI_API_KEY)
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
    "files": db['chat_files'],  # 발화별 저장
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
    # NOTE: views.py uses "session_5" style, so match that format (underscore)
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
    """LLM을 통해 com_type을 추론 (맥락 반영 가능)
       전역 com_type_chain 사용 -> 매 호출 프롬프트/체인 재생성 방지
    """
    context = ""
    if chat_history:
        # chat_history는 dict list 형태 (role, message) 가정
        context = "\n".join([f"{msg['role']}: {msg['message']}" for msg in chat_history[-5:]])

    # 체인 재사용: com_type_chain 에서 predict 사용
    try:
        result = com_type_chain.predict(context=context, text=user_input)
    except Exception as e:
        # LLM 호출 실패 시 빈 문자열 반환 (상위에서 룰로 보완)
        result = ""
    if isinstance(result, dict):
        raw = result.get("text") or result.get("output") or str(result)
    else:
        raw = str(result)

    return truncate_to_full_sentence(raw).strip()


def extract_fields(user_input, chat_history=None):
    """
    우선 룰 기반으로 간단히 추출하고, 없으면 infer_com_type_with_llm 호출.
    -> 이렇게 하면 사용자가 '추가요청' 같은 키워드를 명시했을 때 LLM을 거치지 않아도 됨.
    """
    data = {}

    lowered = user_input.replace(" ", "").lower()

    # 룰 기반 매핑 (빠르게 처리하여 반복 응답 방지)
    if any(k in lowered for k in ["청소", "청소요청", "치우", "청소해"]):
        data["com_type"] = "청소요청"
    elif any(k in lowered for k in ["수리", "수리요청", "고장", "수선"]):
        data["com_type"] = "수리요청"
    elif any(k in lowered for k in ["추가", "추가요청", "더", "설치"]):
        data["com_type"] = "추가요청"
    elif any(k in lowered for k in ["기타", "기타민원"]):
        data["com_type"] = "기타민원"
    else:
        # 룰로 못 잡으면 LLM 시도
        raw_com_type = infer_com_type_with_llm(user_input, chat_history)
        cleaned = raw_com_type.replace(" ", "")

        # 부분 일치 허용
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


# chatbot_core.py의 handle_complain_submit 함수 수정
def handle_complain_submit(user_input, username, session_id, chat_history=None):
    extracted_fields = extract_fields(user_input, chat_history)
    com_type = extracted_fields.get("com_type")

    if com_type:
        response = f"네, 민원 유형이 {com_type}으로 확인되었습니다. 더 자세한 내용을 말씀해주시면 접수해 드릴게요."
    else:
        response = "쓰레기와 관련된 민원으로 보입니다. 어떤 유형인가요? (청소요청, 수리요청, 추가요청, 기타민원)"

    # 추출된 com_type을 딕셔너리에 포함하여 반환
    return {"response": response, "com_type": com_type}


# handle_trash_finder 함수는 딕셔너리를 반환하도록 변경합니다.
def handle_trash_finder(user_input, username, session_id):
    response = trash_chain.run({"user_input": user_input})
    final_response = truncate_to_full_sentence(response)

    return {"response": final_response}


# chatbot_router 함수를 아래와 같이 변경합니다.
# 이제 각 핸들러 함수가 딕셔너리를 반환하므로, 이를 받아서 그대로 반환하면 됩니다.
def chatbot_router(user_input, username, session_id=None, scenario_id=None):
    start_time = time.time()

    if session_id is None:
        session_id = generate_session_id()
    if scenario_id is None:
        scenario_id = classify_scenario(user_input)

    # 인사만 처리 (저장은 views에서 함)
    if is_greeting(user_input):
        response = "안녕하세요! 무엇을 도와드릴까요?"
        return {"response": response, "session_id": session_id}

    if scenario_id == "complain_submit":
        # handle_complain_submit이 딕셔너리를 반환하도록 변경했으므로, 그대로 반환
        result = handle_complain_submit(user_input, username, session_id)
        result["session_id"] = session_id  # 세션 ID를 추가
        return result
    elif scenario_id == "trash_finder":
        result = handle_trash_finder(user_input, username, session_id)
        result["session_id"] = session_id
        return result
    else:
        response = "지원하지 않는 질문입니다."
        return {"response": response, "session_id": session_id}
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
    # NOTE: views.py uses "session_5" style, so match that format (underscore)
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
    """LLM을 통해 com_type을 추론 (맥락 반영 가능)
       전역 com_type_chain 사용 -> 매 호출 프롬프트/체인 재생성 방지
    """
    context = ""
    if chat_history:
        # chat_history는 dict list 형태 (role, message) 가정
        context = "\n".join([f"{msg['role']}: {msg['message']}" for msg in chat_history[-5:]])

    # 체인 재사용: com_type_chain 에서 predict 사용
    try:
        result = com_type_chain.predict(context=context, text=user_input)
    except Exception as e:
        # LLM 호출 실패 시 빈 문자열 반환 (상위에서 룰로 보완)
        result = ""
    if isinstance(result, dict):
        raw = result.get("text") or result.get("output") or str(result)
    else:
        raw = str(result)

    return truncate_to_full_sentence(raw).strip()

def extract_fields(user_input, chat_history=None):
    """
    우선 룰 기반으로 간단히 추출하고, 없으면 infer_com_type_with_llm 호출.
    -> 이렇게 하면 사용자가 '추가요청' 같은 키워드를 명시했을 때 LLM을 거치지 않아도 됨.
    """
    data = {}

    lowered = user_input.replace(" ", "").lower()

    # 룰 기반 매핑 (빠르게 처리하여 반복 응답 방지)
    if any(k in lowered for k in ["청소", "청소요청", "치우", "청소해"]):
        data["com_type"] = "청소요청"
    elif any(k in lowered for k in ["수리", "수리요청", "고장", "수선"]):
        data["com_type"] = "수리요청"
    elif any(k in lowered for k in ["추가", "추가요청", "더", "설치"]):
        data["com_type"] = "추가요청"
    elif any(k in lowered for k in ["기타", "기타민원"]):
        data["com_type"] = "기타민원"
    else:
        # 룰로 못 잡으면 LLM 시도
        raw_com_type = infer_com_type_with_llm(user_input, chat_history)
        cleaned = raw_com_type.replace(" ", "")

        # 부분 일치 허용
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


# chatbot_core.py의 handle_complain_submit 함수 수정
def handle_complain_submit(user_input, username, session_id, chat_history=None):
    cached = complaint_cache.get(session_id, {})
    extracted = extract_fields(user_input, chat_history)
    cached.update(extracted)

    response = (
        "쓰레기와 관련된 민원으로 보입니다. "
        "어떤 유형인가요? (청소요청, 수리요청, 추가요청, 기타민원)"
    )
    # 💡 com_type을 추출했다면, 캐시를 갱신하고 응답을 자연스럽게 수정
    if cached.get("com_type"):
        response = f"네, 민원 유형이 {cached['com_type']}으로 확인되었습니다. 민원 접수해 드릴게요."
        # 이 시점에서 캐시를 지우지 말고, views.py에서 사용하도록 유지
        complaint_cache[session_id] = cached
    else:
        # com_type이 아직 파악되지 않은 경우
        complaint_cache[session_id] = cached

    # 💡 추출된 com_type을 반환 딕셔너리에 포함
    return {"response": response, "com_type": cached.get("com_type")}



def handle_trash_finder(user_input, username, session_id):
    response = trash_chain.run({"user_input": user_input})
    final_response = truncate_to_full_sentence(response)

    return final_response

def chatbot_router(user_input, username, session_id=None, scenario_id=None):
    start_time = time.time()

    if session_id is None:
        session_id = generate_session_id()
    if scenario_id is None:
        scenario_id = classify_scenario(user_input)

    # 인사만 처리 (저장은 views에서 함)
    if is_greeting(user_input):
        response = "안녕하세요! 무엇을 도와드릴까요?"
        print(f"[DEBUG] chatbot_router total processing time: {time.time() - start_time:.2f}s")
        return {"response": response, "session_id": session_id}

    if scenario_id == "complain_submit":
        # 💡 handle_complain_submit이 딕셔너리를 반환하도록 변경했으므로, 그대로 반환
        result = handle_complain_submit(user_input, username, session_id)
        return {"response": result['response'], "com_type": result.get("com_type"), "session_id": session_id}
    elif scenario_id == "trash_finder":
        response = handle_trash_finder(user_input, username, session_id)
        return {"response": response, "session_id": session_id}
    else:
        response = "지원하지 않는 질문입니다."
        return {"response": response, "session_id": session_id}

    print(f"[DEBUG] chatbot_router total processing time: {time.time() - start_time:.2f}s")
    return {"response": response, "session_id": session_id}
