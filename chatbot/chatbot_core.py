import os, re
from datetime import datetime, timezone
import time

import logger
from pymongo import MongoClient, ReturnDocument
from dotenv import load_dotenv
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
    MessagesPlaceholder
)
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.output_parsers import StrOutputParser
from chromadb import HttpClient
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_chroma import Chroma
from konlpy.tag import Okt
import logging
from langchain.chains import create_retrieval_chain
from langchain_core.documents import Document

from config import settings

# 💡 [추가] 거리 계산을 위한 import
from math import radians, sin, cos, sqrt, atan2

# 💡 [추가] TrashLoc 모델 import (사용자 요청에 따라 경로를 'common.models'로 가정)
try:
    from common.models import TrashLoc
except ImportError:
    logger.error("common.models.TrashLoc을 import 할 수 없습니다. 쓰레기통 위치 조회 기능이 제한됩니다.")
    TrashLoc = None

logger = logging.getLogger(__name__)

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client['complaints_db']
COLLECTIONS = {
    "history": db['chat_history'],
    "files": db['chat_files'],
    "complaints": db['complaints'],
}

llm = ChatOpenAI(model_name="gpt-4o-mini", temperature=0.5, max_tokens=70, api_key=settings.OPENAI_API_KEY)
embeddings = OpenAIEmbeddings(api_key=settings.OPENAI_API_KEY)
okt = Okt()

CHROMA_DB_HOST = os.getenv("CHROMA_DB_HOST")

chroma_client = None
if CHROMA_DB_HOST:
    try:
        chroma_client = HttpClient(host=CHROMA_DB_HOST, port=8000)
    except Exception as e:
        logger.error(f"ChromaDB 연결 실패: {e}", exc_info=True)

vector_store = Chroma(
    collection_name="complaint_embeddings",
    embedding_function=OpenAIEmbeddings(api_key=settings.OPENAI_API_KEY),
    persist_directory="./chroma_db",
    client=chroma_client
)


# 💡 [추가] Haversine 함수 정의
def haversine(lat1, lon1, lat2, lon2):
    """두 지점 간의 거리를 Haversine 공식을 이용해 미터 단위로 계산합니다."""
    R = 6371000  # 지구의 반지름 (미터)

    lat1_rad, lon1_rad = radians(lat1), radians(lon1)
    lat2_rad, lon2_rad = radians(lat2), radians(lon2)

    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad

    a = sin(dlat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    distance = R * c
    return distance


# --- 프롬프트 정의 ---
trash_prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template("당신은 쓰레기통 위치 안내 챗봇입니다."),
    HumanMessagePromptTemplate.from_template("사용자 질문: {user_input}")
])
trash_chain = trash_prompt | llm

# 수정된 프롬프트
_complaint_chain_prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(
        "당신은 친절하지만 정확한 민원 접수 챗봇입니다. 사용자의 불편함에 공감하면서도 빠르게 민원을 제보할 수 있게 질문하며 대화하세요."
        "단계별로 추론해서 답변해"
        "사용자의 민원을 '청소요청', '수리요청', '추가요청', '기타민원' 중 하나 또는 여러 개로 분류하세요. "
        "청소요청, 수리요청, 추가요청, 기타민원 중에 어떤 건지 넣어줘. 중복도 가능해. "
        "청소요청은 쓰레기통이나 쓰레기통이 없어도 가능한 요청이고, "
        "수리요청은 기존 쓰레기통의 파손이나 고장 관련 내용이야. "
        "추가요청은 쓰레기통이 없는 곳에 **새로 설치하거나 더 많이** 만들어 달라는 내용이야. "
        "기타민원은 그 이외의 모든 민원(무단투기 단속, 정책 제안 등)을 포함해. "
        "만약 '무단투기', '상습적으로 버린다', '자주 버린다' 같은 키워드가 포함되면 '기타민원'으로 분류하세요."
        "만약 여러 개의 유형이라면 쉼표(,)로 구분하세요. (예: 청소요청,기타민원)"
        "만약 분류가 명확하지 않다면, 공감하며 자연스러운 질문을 생성하여 추가 정보를 요청하세요."
        "예시: '많이 불편하셨겠어요. 쓰레기통이 가득 찬 건가요, 아니면 주변에 쓰레기가 쌓여 있는 건가요?'"
        "오직 분류 결과(유형)나 질문(문장)만 반환하세요."
        "기타 민원의 경우에는 정책 제안이나 쓰레기 무단투기 단속 강화 등이 있을 수 있어."
        "민원 타입이 추론되면 사용자에게 해당 유형이 맞는지 물어보고 확정하세요. "
        "예시: '쓰레기가 많이 쌓여서 청소요청이 필요하시다는 말씀이실까요?'"
        "사용자가 '네', '맞아', '어', '응', '접수해줘'와 같이 긍정적으로 확인하면, 최종적으로 '민원 접수가 완료되었습니다.'와 같은 확정 문장을 반환하세요."
        "최대한 간결하고 짧게 답변하세요."
    ),
    MessagesPlaceholder(variable_name="chat_history"),
    HumanMessagePromptTemplate.from_template("이전 민원 기록: {retrieved_context}\n\n사용자 발화: {user_input}")
])
complaint_chain = _complaint_chain_prompt | llm | StrOutputParser()

# 💡 대화 내용을 요약하는 새로운 프롬프트
_summary_prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(
        "당신은 민원 내용을 정확하게 요약하는 전문 요약가입니다. 다음 대화 내용을 민원 담당자가 이해하기 쉽게 하나의 간결한 문장으로 요약해 주세요. 불필요한 인사말이나 확인 문구(예: '네', '맞아')는 제거하고, 핵심적인 민원 내용과 상황만을 포함해야 합니다. 사용자의 발화만 요약에 포함하세요."
    ),
    MessagesPlaceholder(variable_name="chat_history")
])
summary_chain = _summary_prompt | llm | StrOutputParser()


# --- 전처리 함수 ---
def preprocess_text(text):
    """
    텍스트를 전처리하여 명사만 추출하고 불용어를 제거합니다.
    """
    if not isinstance(text, str):
        return ""

    # 1. 특수문자 제거
    # 한글, 영문, 숫자, 공백만 남깁니다.
    text = re.sub(r'[^\s\w]', '', text)

    # 2. Okt를 사용하여 명사 추출
    nouns = okt.nouns(text)

    # 3. 불용어 제거
    # 사용자가 언급한 조사들을 포함하여 더 포괄적인 불용어 목록을 정의합니다.
    stopwords = [
        '은', '는', '이', '가', '을', '를', '의', '에', '에서', '에게', '로', '으로',
        '와', '과', '고', '에게', '한테', '처럼', '만큼', '다', '뭐', '에는', '만',
        '되', '해',
        '것', '곳', '다', '등', '내', '저', '수', '점', '말', '그', '때', '후', '때문'
    ]
    processed_text = ' '.join([word for word in nouns if word not in stopwords])

    return processed_text


# --- 유틸리티 함수: 사용자 입력 처리 및 데이터 조회 ---

def is_greeting(text):
    """사용자 입력이 인사말인지 확인합니다."""
    GREETINGS = ["안녕하세요", "안녕", "hi", "hello", "반갑습니다", "안녕하십니까"]
    return any(greet in text.lower() for greet in GREETINGS)


def classify_scenario(user_input):
    """사용자 입력에 따라 시나리오를 분류합니다."""
    if any(word in user_input for word in ["쓰레기", "청소", "신고", "넘침", "민원"]):
        return "complain_submit"
    if any(word in user_input for word in ["쓰레기통", "어디", "위치", "찾아줘"]):
        return "trash_finder"
    return "unknown"


def get_chat_history_from_db(session_id):
    """MongoDB에서 채팅 기록을 불러옵니다."""
    return list(COLLECTIONS["history"].find({"session_id": session_id}).sort("created_at", 1))


def get_full_user_complaint_from_history(chat_history):
    """채팅 기록에서 사용자의 모든 민원 관련 발화를 추출합니다."""
    full_complaint_text = []
    # complain_submit 시나리오에서 사용자의 발화만 추출
    for chat in chat_history:
        if chat.get('scenario_id') == 'complain_submit' and chat['role'] == 'user':
            full_complaint_text.append(chat['content'])
    return " ".join(full_complaint_text).strip()


def get_langchain_history(chat_history):
    """채팅 기록을 LangChain 메시지 형식으로 변환합니다."""
    return [HumanMessage(content=chat['content']) if chat['role'] == 'user' else AIMessage(content=chat['content']) for
            chat in chat_history]


def get_com_types_from_history(chat_history):
    """채팅 기록에서 봇이 추론했던 모든 민원 유형을 추출합니다."""
    all_types = set()
    for chat in chat_history:
        if chat.get('scenario_id') == 'complain_submit' and chat['role'] == 'assistant':
            types = chat.get('metadata', {}).get('com_type', [])
            for t in types:
                all_types.add(t)
    return list(all_types)


# 💡 수정된 함수: ChromaDB 검색 로직을 as_retriever()를 사용하도록 변경
def retrieve_complaint_history_with_filter(query, com_types, num_results=3):
    """
    ChromaDB에서 유사한 민원 기록을 검색하고, 제공된 민원 유형으로 결과를 필터링합니다.
    """
    preprocessed_query = preprocess_text(query)

    # ❗️ 수정된 부분: ChromaDB가 지원하는 '$eq', '$in' 연산자만 사용
    where_filter = None
    if com_types:
        where_filter = {"com_type": {"$in": com_types}}

    # ❗️ 수정된 부분: 필터가 있을 때만 `filter` 인자를 전달
    if where_filter:
        retriever = vector_store.as_retriever(
            search_kwargs={"k": num_results, "filter": where_filter}
        )
    else:
        retriever = vector_store.as_retriever(
            search_kwargs={"k": num_results}
        )

    retrieved_docs = retriever.get_relevant_documents(preprocessed_query)

    context = ""
    if retrieved_docs:
        doc = retrieved_docs[0]
        context = f"유사 민원: {doc.page_content}\n"
    return context.strip()


def extract_complaint_types(llm_output):
    """LLM 응답에서 민원 유형을 추출합니다."""
    known_types = ["청소요청", "수리요청", "추가요청", "기타민원"]
    return [known_type for known_type in known_types if known_type in llm_output]


def truncate_to_full_sentence(text):
    """텍스트를 완전한 문장 단위로 자릅니다."""
    sentences = re.findall(r'.+?[.!?](?:\s|$)', text)
    return ''.join(sentences).strip()


def generate_session_id():
    """MongoDB 카운터를 사용하여 새로운 세션 ID를 생성합니다."""
    counter = COLLECTIONS['history'].database.counters.find_one_and_update(
        {'_id': 'session_id'},
        {'$inc': {'seq': 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    return f"session_{counter['seq']}"


# 💡 대화 내용을 요약하는 새로운 함수
def summarize_conversation(chat_history):
    """
    주어진 대화 기록을 바탕으로 민원 내용을 요약합니다.
    """
    langchain_chat_history = get_langchain_history(chat_history)
    try:
        summary_result = summary_chain.invoke({"chat_history": langchain_chat_history})
        return summary_result.strip()
    except Exception as e:
        logger.error(f"대화 요약 실패: {e}", exc_info=True)
        return get_full_user_complaint_from_history(chat_history)  # 요약 실패 시 기존 방식(전체 대화 합치기)으로 대체


# --- 메인 핸들러 함수: 시나리오별 응답 처리 ---
def handle_complain_submit(user_input, username, session_id, chat_history):
    """민원 접수 시나리오를 처리하고 라우터에 결과를 반환합니다."""
    langchain_chat_history = get_langchain_history(chat_history)

    current_com_types = get_com_types_from_history(chat_history)

    retrieved_context = retrieve_complaint_history_with_filter(user_input, current_com_types)

    try:
        llm_output = complaint_chain.invoke({
            "chat_history": langchain_chat_history,
            "user_input": user_input,
            "retrieved_context": retrieved_context
        }).strip()
    except Exception as e:
        logger.error(f"Complaint chain failed: {e}", exc_info=True)
        return {"response": "민원 유형을 파악하는 데 실패했습니다. 다시 말씀해주시겠어요?", "com_type": None, "is_final": False}

    llm_types = extract_complaint_types(llm_output)

    is_final = ("완료되었습니다." in llm_output or "제보하겠습니다." in llm_output or "접수되었습니다." in llm_output)

    if is_final:
        com_types = get_com_types_from_history(chat_history)
        com_types.extend(extract_complaint_types(user_input))
        com_types = list(set(com_types))

        summary = summarize_conversation(chat_history)
        return {"response": llm_output, "com_type": com_types, "is_final": is_final, "summary": summary}
    else:
        com_types = llm_types
        return {"response": llm_output, "com_type": com_types, "is_final": is_final}


# 💡 [수정] handle_trash_finder 함수: 주변 쓰레기통 유무 확인 로직 추가 및 인자 추가
def handle_trash_finder(user_input, username, session_id, com_location=None):
    """쓰레기통 위치 안내 시나리오를 처리하고 라우터에 결과를 반환합니다."""

    user_lat, user_lon = None, None

    # 1. 현 위치 (위도/경도) 가져오기: temp_com_location을 바탕으로 ChatHistory에서 조회 (가장 최근)
    # 💡 [핵심] com_location이 전달되었더라도, 실제 위치(lat/lon)는 ChatHistory에서 가져와야 함.
    #    (views.py에서 위치 확인 시 lat/lon을 ChatHistory에 저장한다고 가정)
    location_doc = COLLECTIONS["history"].find_one(
        {"session_id": session_id, "role": "user", "latitude": {"$exists": True, "$ne": None}},
        sort=[("created_at", -1)]
    )

    if location_doc and location_doc.get("latitude") and location_doc.get("longitude"):
        try:
            user_lat = float(location_doc["latitude"])
            user_lon = float(location_doc["longitude"])
        except (ValueError, TypeError):
            user_lat, user_lon = None, None

    # 2. 위치 정보가 있을 경우에만 쓰레기통 조회 로직 실행
    if user_lat is not None and user_lon is not None and TrashLoc:

        # 3. 쓰레기통 데이터 조회 및 거리 계산
        nearby_counts = {100: 0, 200: 0, 300: 0}  # 미터
        try:
            # 💡 [Django Model 사용 가정] TrashLoc.objects.all()로 모든 쓰레기통 조회
            all_trashcans = TrashLoc.objects.all()

            for t in all_trashcans:
                # DB의 lat, lon이 DecimalField이므로, float으로 변환
                if t.t_lat and t.t_lon:
                    t_lat = float(t.t_lat)
                    t_lon = float(t.t_lon)

                    distance_m = haversine(user_lat, user_lon, t_lat, t_lon)

                    # 300m 이내만 계산 (최대 범위)
                    if distance_m <= 300:
                        if distance_m <= 100:
                            nearby_counts[100] += 1
                        if distance_m <= 200:
                            nearby_counts[200] += 1
                        if distance_m <= 300:
                            nearby_counts[300] += 1

            # 4. 응답 생성
            response_parts = []

            # 100m 이내 개수 확인
            if nearby_counts[100] > 0:
                response_parts.append(f"현재 위치 주변 100m 이내에 쓰레기통 {nearby_counts[100]}개가 있습니다.")
            else:
                response_parts.append("현재 위치 주변 100m 이내에는 쓰레기통이 없습니다.")

            # 200m 이내 추가 확인 (100m 초과 ~ 200m 이내)
            if nearby_counts[200] > nearby_counts[100]:
                response_parts.append(f"200m 이내로 범위를 넓히면 총 {nearby_counts[200]}개의 쓰레기통이 있습니다.")

            # 300m 이내 추가 확인 (200m 초과 ~ 300m 이내)
            if nearby_counts[300] > nearby_counts[200]:
                response_parts.append(f"300m 이내로 범위를 넓히면 총 {nearby_counts[300]}개의 쓰레기통이 있습니다.")

            if nearby_counts[300] == 0 and nearby_counts[100] == 0:
                response_parts.append("300m 이내에는 쓰레기통이 없는 것 같아요. 다른 곳을 찾아보시겠어요?")

            # LLM 체인을 타지 않고, 위치 정보 기반으로 직접 생성한 응답을 반환
            return {"response": " ".join(response_parts), "is_final": False}

        except Exception as e:
            logger.error(f"쓰레기통 위치 조회 중 오류 발생: {e}", exc_info=True)
            # 오류 발생 시, 일반적인 챗봇 응답으로 대체
            pass  # 아래 기존 LLM 호출 로직으로 이동

    # 5. 위치 정보가 없거나, 조회 중 오류가 발생했거나, 기타 일반적인 'trash_finder' 질문일 경우 LLM 호출 (기존 로직)
    response = trash_chain.invoke({"user_input": user_input})
    final_response = truncate_to_full_sentence(response.content)
    return {"response": final_response, "is_final": False}


# --- 메인 라우터 함수: 전체 대화의 흐름 제어 ---
# 💡 [수정] com_location 인자를 handle_trash_finder로 전달하도록 수정
def chatbot_router(user_input, username, session_id=None, scenario_id=None, com_location=None):
    """
    사용자 입력에 따라 적절한 챗봇 시나리오를 라우팅합니다.
    """
    if session_id is None:
        session_id = generate_session_id()

    # 💡 [핵심] 위치 확인 메시지 패턴을 확인
    is_location_confirmed = False
    if scenario_id == "trash_finder" and user_input.startswith("위치확인_주소:"):
        location_address = user_input.replace("위치확인_주소:", "").strip()
        is_location_confirmed = True

        # 💡 챗봇 응답을 즉시 반환 (요청하신 응답)
        return {
            "response": f"위치 확인했습니다. 무엇을 도와드릴까요?",
            "session_id": session_id,
            "is_final": False  # 위치 확인 후 대화를 계속해야 하므로 False
        }

    if scenario_id is None:
        scenario_id = classify_scenario(user_input)

    chat_history = get_chat_history_from_db(session_id)

    if is_greeting(user_input):
        return {"response": "안녕하세요! 무엇을 도와드릴까요?", "session_id": session_id, "is_final": False}

    if scenario_id == "complain_submit":
        result = handle_complain_submit(user_input, username, session_id, chat_history)
        result["session_id"] = session_id
        return result
    elif scenario_id == "trash_finder":
        # 💡 [수정] com_location 인자를 handle_trash_finder로 전달
        result = handle_trash_finder(user_input, username, session_id, com_location)
        result["session_id"] = session_id
        return result
    else:
        response = "지원하지 않는 질문입니다."
        return {"response": response, "session_id": session_id, "is_final": False}