import os, re
from datetime import datetime, timezone
import time
from pymongo import MongoClient, ReturnDocument
from dotenv import load_dotenv
from langchain.chat_models import ChatOpenAI
from langchain.chains import LLMChain
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import MongoDBAtlasVectorSearch
from config import settings
import logging

logger = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client['complaints_db']
COLLECTIONS = {
    "history": db['chat_history'],
    "files": db['chat_files'],
    "complaints": db['complaints'],
    "embeddings": db['complaint_embeddings']  # 새로운 임베딩 컬렉션
}

# --- LLM 및 임베딩 세팅 ---
llm = ChatOpenAI(model_name="gpt-4o-mini", temperature=0.7, max_tokens=100, api_key=settings.OPENAI_API_KEY)
embeddings = OpenAIEmbeddings(api_key=settings.OPENAI_API_KEY)

# 💡 Vector Store 인스턴스 생성
vector_store = MongoDBAtlasVectorSearch(
    collection=COLLECTIONS["embeddings"],
    embedding=embeddings,
    index_name="vector_index"
)

# --- 프롬프트 ---
trash_prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template("당신은 쓰레기통 위치 안내 챗봇입니다."),
    HumanMessagePromptTemplate.from_template("사용자 질문: {user_input}")
])
trash_chain = LLMChain(llm=llm, prompt=trash_prompt)

# 💡 민원 유형을 분류하고, 필요시 질문을 생성하는 통합 프롬프트
_complaint_chain_prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(
        "당신은 친절한 민원 접수 챗봇입니다. 사용자의 민원 유형을 '청소요청', '수리요청', '추가요청' 중 하나로 분류하세요. "
        "만약 분류가 명확하지 않다면, 사용자에게 민원 유형을 묻는 자연스러운 질문을 생성하세요."
        "질문을 할 때는 단계적으로 물어봐."
        "청소가 어떨 때 필요한 건지. 그냥 청소인지. 쓰레기통을 비워야 하는지 동시인 건지."
        "예시: '쓰레기통이 가득 찼나요, 아니면 고장난 건가요?'"
        "만약 사용자가 민원 유형을 확정하면, '확정'이라고만 응답하세요. "
        "오직 분류 결과(유형)나 질문(문장)만 반환하세요."
    ),
    HumanMessagePromptTemplate.from_template(
        "이전 민원 기록: {retrieved_context}\n\n대화 내용: {chat_history}\n사용자 발화: {user_input}")
])
complaint_chain = LLMChain(llm=llm, prompt=_complaint_chain_prompt)

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


# 💡 새로운 함수: 과거 민원 기록 검색 (수정됨)
def retrieve_complaint_history(query, username, num_results=3):  # num_results를 3개로 늘려 검색 후 필터링에 대비

    # 'filter' 인자 없이 벡터 검색 실행
    retrieved_docs_with_scores = vector_store.similarity_search_with_score(
        query=query,
        k=num_results
    )

    context = ""
    user_specific_docs = []

    # 검색된 문서들을 순회하며 username으로 필터링
    for doc, score in retrieved_docs_with_scores:
        if doc.metadata.get("username") == username:
            user_specific_docs.append((doc, score))

    # 필터링된 문서 중 상위 1개만 사용
    if user_specific_docs:
        doc, score = user_specific_docs[0]
        context = f"유사 민원: {doc.page_content} (관련도: {score:.2f})\n"

    return context.strip()


def handle_complain_submit(user_input, username, session_id, chat_history=None):
    # 💡 1단계: 첫 발화인 경우, 무조건 질문을 던져 사용자의 의도를 확인
    if not chat_history:
        response = "어떤 종류의 민원인가요? 청소가 필요한지, 아니면 수리나 추가 요청인지 말씀해주세요."
        return {"response": response, "com_type": None}

    # 💡 2단계: 두 번째 턴부터는 LLM을 통해 민원 유형 파악
    chat_history_text = "\n".join([f"{chat['role']}: {chat['content']}" for chat in chat_history])

    # 💡 과거 민원 기록 검색
    retrieved_context = retrieve_complaint_history(user_input, username)

    try:
        # LLM 호출 시 과거 기록을 함께 전달
        llm_output = complaint_chain.predict(
            chat_history=chat_history_text,
            user_input=user_input,
            retrieved_context=retrieved_context
        ).strip()
    except Exception as e:
        logger.error(f"Complaint chain failed: {e}", exc_info=True)
        llm_output = "민원 유형을 파악하는 데 실패했습니다. 다시 말씀해주시겠어요?"

    if llm_output in ["청소요청", "수리요청", "추가요청", "기타민원"]:
        response = f"네, 민원 유형이 **{llm_output}**으로 확인되었습니다. 접수되었습니다."
        com_type = llm_output
    elif llm_output == "확정":
        last_bot_message = next(
            (chat for chat in reversed(chat_history) if chat['role'] == 'assistant' and "민원 유형이" in chat['content']),
            None)
        if last_bot_message:
            match = re.search(r'\*\*(.*?)\*\*', last_bot_message['content'])
            if match:
                confirmed_type = match.group(1)
                response = f"네, **{confirmed_type}**에 대한 상세 내용을 말씀해주시면 감사하겠습니다."
                com_type = confirmed_type
            else:
                response = "이전에 어떤 민원이었는지 확인이 어렵습니다. 다시 한번 말씀해주시겠어요?"
                com_type = None
        else:
            response = "민원 유형이 파악되지 않았습니다. 다시 말씀해주세요."
            com_type = None
    else:
        response = llm_output
        com_type = None

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

    chat_history = list(COLLECTIONS["history"].find({"session_id": session_id}).sort("created_at", 1))

    if is_greeting(user_input):
        response = "안녕하세요! 무엇을 도와드릴까요?"
        return {"response": response, "session_id": session_id}

    if scenario_id == "complain_submit":
        result = handle_complain_submit(user_input, username, session_id, chat_history)
        result["session_id"] = session_id
        return result
    elif scenario_id == "trash_finder":
        result = handle_trash_finder(user_input, username, session_id)
        result["session_id"] = session_id
        return result
    else:
        response = "지원하지 않는 질문입니다."
        return {"response": response, "session_id": session_id}