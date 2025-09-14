import os, re
from datetime import datetime, timezone
import time
from pymongo import MongoClient, ReturnDocument
from dotenv import load_dotenv

# 💡 **[수정]** 핵심 기능: langchain-core 패키지에서 필요한 모든 것을 임포트합니다.
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
    MessagesPlaceholder
)
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.output_parsers import StrOutputParser # 💡 추가된 import
# 💡 **langchain_chroma 대신 직접 chromadb 클라이언트를 사용**
from chromadb import HttpClient

# 외부 연동: langchain-openai, langchain-chroma 등에서 임포트
from langchain_openai import ChatOpenAI
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from config import settings
import logging

logger = logging.getLogger(__name__)

# .env 파일에서 환경 변수 로드
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client['complaints_db']
COLLECTIONS = {
    "history": db['chat_history'],
    "files": db['chat_files'],
    "complaints": db['complaints'],
}

# --- LLM 및 임베딩 설정 ---
# 💡 LLM(대형 언어 모델)과 임베딩 모델을 설정하는 섹션입니다.
llm = ChatOpenAI(model_name="gpt-4o-mini", temperature=0.7, max_tokens=80, api_key=settings.OPENAI_API_KEY)
embeddings = OpenAIEmbeddings(api_key=settings.OPENAI_API_KEY)

# 💡 ChromaDB 호스트 IP를 환경 변수에서 가져옵니다.
CHROMA_DB_HOST = os.getenv("CHROMA_DB_HOST")

# 💡 **[핵심 수정]** 직접 chromadb 클라이언트를 생성합니다.
chroma_client = HttpClient(
    host=CHROMA_DB_HOST,
    port=8000
)

# 💡 생성한 클라이언트를 vector_store에 전달합니다.
vector_store = Chroma(
    collection_name="complaint_embeddings",
    embedding_function=embeddings,
    client=chroma_client  # 💡 client_settings 대신 client를 사용
)

# --- 프롬프트 정의 ---
# 💡 챗봇의 역할을 정의하는 프롬프트들을 설정하는 섹션입니다.
# 💡 **[수정]** 더 이상 LLMChain을 사용하지 않고, Runnable Sequence를 사용합니다.
trash_prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template("당신은 쓰레기통 위치 안내 챗봇입니다."),
    HumanMessagePromptTemplate.from_template("사용자 질문: {user_input}")
])
trash_chain = trash_prompt | llm

# 💡 민원 유형을 분류하고, 필요시 질문을 생성하는 통합 프롬프트입니다.
# 💡 **[핵심 수정]** 프롬프트에 더 구체적인 민원 유형을 추가했습니다.
_complaint_chain_prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(
        "당신은 친절한 민원 접수 챗봇입니다. 사용자의 민원 유형을 '청소요청', '수리요청', '추가요청', '쓰레기통 청소요청', '쓰레기통 수리요청' 중 하나 또는 여러 개로 분류하세요. "
        "만약 여러 개의 유형이라면 쉼표(,)로 구분하세요. (예: 청소요청,쓰레기통 수리요청)"
        "만약 분류가 명확하지 않다면, 사용자에게 민원 유형을 묻는 자연스러운 질문을 생성하세요."
        "질문을 할 때는 단계적으로 물어봐."
        "청소가 어떨 때 필요한 건지. 그냥 청소인지. 쓰레기통을 비워야 하는지 동시인 건지."
        "예시: '쓰레기통이 가득 찼나요, 아니면 고장난 건가요?'"
        "만약 사용자가 민원 유형을 확정하면, '확정'이라고만 응답하세요. "
        "오직 분류 결과(유형)나 질문(문장)만 반환하세요."
    ),
    MessagesPlaceholder(variable_name="chat_history"),  # 💡 **[수정]** 여기에 대화 기록이 들어갑니다.
    HumanMessagePromptTemplate.from_template("이전 민원 기록: {retrieved_context}\n\n사용자 발화: {user_input}")
])
# 💡 **[수정]** LLMChain 대신 Runnable Sequence를 사용합니다.
complaint_chain = _complaint_chain_prompt | llm | StrOutputParser()

# --- 유틸리티 함수 ---
# 💡 챗봇의 동작을 돕는 보조 함수들입니다.
GREETINGS = ["안녕하세요", "안녕", "hi", "hello", "반갑습니다", "안녕하십니까"]


def is_greeting(text):
    """사용자 입력이 인사말인지 확인합니다."""
    return any(greet in text.lower() for greet in GREETINGS)


def classify_scenario(user_input):
    """사용자 입력에 따라 '민원 접수' 또는 '쓰레기통 찾기' 시나리오로 분류합니다."""
    if any(word in user_input for word in ["쓰레기", "청소", "신고", "넘침", "민원"]):
        return "complain_submit"
    if any(word in user_input for word in ["쓰레기통", "어디", "위치", "찾아줘"]):
        return "trash_finder"
    return "unknown"


def truncate_to_full_sentence(text):
    """문장을 완전한 문장 단위로 자릅니다."""
    sentences = re.findall(r'.+?[.!?](?:\s|$)', text)
    return ''.join(sentences).strip()


# --- MongoDB ID 생성 함수 ---
# 💡 MongoDB의 카운터를 사용하여 고유한 ID를 생성합니다.
def generate_session_id():
    """새로운 세션 ID를 생성합니다."""
    counter = db.counters.find_one_and_update(
        {'_id': 'session_id'},
        {'$inc': {'seq': 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    return f"session_{counter['seq']}"


def generate_chat_id():
    """새로운 채팅 ID를 생성합니다."""
    counter = db.counters.find_one_and_update(
        {'_id': 'chat_id'},
        {'$inc': {'seq': 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    return counter['seq']


# --- 데이터베이스 저장 함수 ---
# 💡 챗봇 대화 기록 및 민원 데이터를 MongoDB에 저장하는 함수들입니다.
def save_chat_history(username, scenario_id, session_id, role, content, is_final=False, metadata=None):
    """챗봇 대화 기록을 MongoDB에 저장합니다."""
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
    """민원 데이터를 MongoDB에 저장합니다."""
    complaint_data["username"] = username
    complaint_data["com_reg_date"] = datetime.now(timezone.utc)
    return COLLECTIONS["complaints"].insert_one(complaint_data).inserted_id


# --- 민원 처리 로직 ---
# 💡 챗봇의 핵심 로직을 담당하는 함수들입니다.
REQUIRED_FIELDS = ["com_type", "lat", "lon"]


def retrieve_complaint_history(query, username, num_results=3):
    """ChromaDB에서 과거 유사 민원 기록을 검색합니다."""
    retrieved_docs_with_scores = vector_store.similarity_search_with_score(
        query=query,
        k=num_results
    )

    context = ""
    if retrieved_docs_with_scores:
        doc, score = retrieved_docs_with_scores[0]
        context = f"유사 민원: {doc.page_content} (관련도: {score:.2f})\n"

    return context.strip()


def handle_complain_submit(user_input, username, session_id, chat_history):
    """민원 접수 시나리오의 대화를 처리합니다."""

    # 💡 **[핵심 수정]** MongoDB의 대화 기록을 LangChain 메시지 객체로 변환합니다.
    langchain_chat_history = []
    for chat in chat_history:
        if chat['role'] == 'user':
            langchain_chat_history.append(HumanMessage(content=chat['content']))
        elif chat['role'] == 'assistant':
            langchain_chat_history.append(AIMessage(content=chat['content']))

    # 💡 **[핵심 수정]** 첫 발화 여부와 상관없이, 대화 기록을 기반으로 LLM이 판단합니다.
    #    별도의 `if not chat_history:` 로직이 필요 없어졌습니다.

    # 💡 과거 민원 기록을 검색합니다.
    retrieved_context = retrieve_complaint_history(user_input, username)

    try:
        # 💡 **[수정]** LangChain Runnable 체인을 호출하여 대화 기록과 함께 예측을 수행합니다.
        llm_output = complaint_chain.invoke({
            "chat_history": langchain_chat_history,
            "user_input": user_input,
            "retrieved_context": retrieved_context
        }).strip()
    except Exception as e:
        logger.error(f"Complaint chain failed: {e}", exc_info=True)
        llm_output = "민원 유형을 파악하는 데 실패했습니다. 다시 말씀해주시겠어요?"

    # 💡 **[핵심 수정]** LLM 응답을 파싱하여 여러 개의 민원 유형을 처리합니다.
    #    응답이 쉼표를 포함하는지 확인하고, 분리합니다.
    if ',' in llm_output:
        com_types = [item.strip() for item in llm_output.split(',')]
    else:
        com_types = [llm_output]

    # 💡 **[핵심 수정]** 파싱된 유형에 따라 응답을 생성합니다.
    #    새로운 유형들을 known_types 리스트에 추가했습니다.
    known_types = ["청소요청", "수리요청", "추가요청", "기타민원", "쓰레기통 청소요청", "쓰레기통 수리요청"]
    is_identified = all(item in known_types for item in com_types)

    if is_identified:
        # 쉼표로 구분된 문자열로 응답 메시지를 생성
        response_types = ', '.join(com_types)
        response = f"네, 민원 유형이 **{response_types}**으로 확인되었습니다. 접수되었습니다."
        com_type = com_types
    elif llm_output == "확정":
        # '확정' 로직은 기존과 동일하게 유지
        last_bot_message = next(
            (chat for chat in reversed(chat_history) if chat['role'] == 'assistant' and "민원 유형이" in chat['content']),
            None)
        if last_bot_message:
            match = re.search(r'\*\*(.*?)\*\*', last_bot_message['content'])
            if match:
                confirmed_type = match.group(1)
                response = f"네, **{confirmed_type}**에 대한 상세 내용을 말씀해주시면 감사하겠습니다."
                com_type = confirmed_type.split(', ') # 여러 유형에 대비하여 리스트로 변환
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
    """쓰레기통 위치 찾기 시나리오의 대화를 처리합니다."""
    response = trash_chain.invoke({"user_input": user_input})
    final_response = truncate_to_full_sentence(response)

    return {"response": final_response}


# --- 메인 라우터 함수 ---
# 💡 사용자 요청을 분석하여 적절한 챗봇 시나리오로 연결하는 핵심 라우터입니다.
def chatbot_router(user_input, username, session_id=None, scenario_id=None):
    """사용자 입력에 따라 적절한 챗봇 시나리오를 호출합니다."""
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