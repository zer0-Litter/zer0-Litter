import os, re
from datetime import datetime, timezone
from pymongo import MongoClient, ReturnDocument
from dotenv import load_dotenv
from langchain.chat_models import ChatOpenAI
from langchain.chains import LLMChain
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate

load_dotenv(os.path.expanduser("~/Users/tasha/Projects/zer0-litter/.env"))
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client['complaints_db']
COLLECTIONS = {
    "history": db['chat_history'],
    "files": db['chat_files'],
    "complaints": db['complaints']
}

# --- LLM 세팅 ---
llm = ChatOpenAI(model_name="gpt-3.5-turbo", temperature=0.7, max_tokens=150)

# --- 프롬프트 ---
trash_prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template("당신은 쓰레기통 위치 안내 챗봇입니다."),
    HumanMessagePromptTemplate.from_template("사용자 질문: {user_input}")
])
trash_chain = LLMChain(llm=llm, prompt=trash_prompt)

complain_prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(
        "당신은 민원 접수 챗봇입니다. 간단한 인사말은 답변하고, 신고 내용 기반으로 필요한 정보를 확인하세요."
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
    return f"session-{counter['seq']}"

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
REQUIRED_FIELDS = ["com_type", "com_contents"]
complaint_cache = {}

def infer_com_type_with_llm(user_input):
    prompt = ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(
            "사용자 입력을 바탕으로 com_type을 '청소요청', '수리요청', '추가요청', '기타민원' 중 하나로 분류하세요."
        ),
        HumanMessagePromptTemplate.from_template("{text}")
    ])
    chain = LLMChain(llm=llm, prompt=prompt)
    raw = chain.run({"text": user_input})
    return truncate_to_full_sentence(raw).strip()

def extract_fields(user_input):
    data = {}
    com_type = infer_com_type_with_llm(user_input).replace(" ", "")
    if com_type in ["청소요청", "수리요청", "추가요청", "기타민원"]:
        data["com_type"] = [com_type]
    data["com_contents"] = user_input
    return data

def is_complete(complaint_data):
    if not complaint_data: return False
    return all(complaint_data.get(f) for f in REQUIRED_FIELDS)

def handle_complain_submit(user_input, username, session_id):
    cached = complaint_cache.get(session_id, {})
    extracted = extract_fields(user_input)
    cached.update(extracted)

    if is_complete(cached):
        final_data = {**cached, "status_id": 1}
        save_complaint(username, final_data)
        complaint_cache.pop(session_id, None)
        response = f"신고가 접수되었습니다. 내용: {cached}"
    else:
        complaint_cache[session_id] = cached
        missing = [f for f in REQUIRED_FIELDS if f not in cached or not cached[f]]
        response = f"추가 정보가 필요합니다: {', '.join(missing)}"

    save_chat_history(username, "complain_submit", session_id, "bot", response)
    return response

def handle_trash_finder(user_input, username, session_id):
    response = trash_chain.run({"user_input": user_input})
    save_chat_history(username, "trash_finder", session_id, "bot", response)
    return truncate_to_full_sentence(response)

def chatbot_router(user_input, username, session_id=None, scenario_id=None):
    if session_id is None:
        session_id = generate_session_id()
    if scenario_id is None:
        scenario_id = classify_scenario(user_input)

    save_chat_history(username, scenario_id, session_id, "user", user_input)

    if is_greeting(user_input):
        response = "안녕하세요! 무엇을 도와드릴까요?"
        save_chat_history(username, scenario_id, session_id, "bot", response)
        return {"response": response, "session_id": session_id}

    if scenario_id == "complain_submit":
        response = handle_complain_submit(user_input, username, session_id)
    elif scenario_id == "trash_finder":
        response = handle_trash_finder(user_input, session_id, username)
    else:
        response = "지원하지 않는 질문입니다."
        save_chat_history(username, scenario_id, session_id, "bot", response)

    return {"response": response, "session_id": session_id}
