from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from .chatbot_core import chatbot_router
from common.models_mongo import ChatHistory, Counter, ChatFiles, Complaints
from datetime import datetime
import logging, os
from uuid import uuid4
from config import settings
from dotenv import load_dotenv
import re
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain.docstore.document import Document as LangchainDocument
from langchain.chains import LLMChain
from bson.objectid import ObjectId

# 💡 로그 설정을 위한 로거 생성
logger = logging.getLogger(__name__)

# 💡 환경 변수(.env 파일) 로드
load_dotenv()

# 💡 ChromaDB 호스트 IP를 환경 변수에서 가져옵니다.
CHROMA_DB_HOST = os.getenv("CHROMA_DB_HOST")

# 💡 ChromaDB 클라이언트 설정. 환경 변수가 존재하면 원격 클라이언트 사용, 아니면 로컬 설정 사용
if CHROMA_DB_HOST:
    from chromadb import HttpClient

    chroma_client = HttpClient(host=CHROMA_DB_HOST, port=8000)
else:
    chroma_client = None

# 💡 OpenAI 임베딩 및 ChromaDB 벡터 저장소 설정
#    persiste_directory를 지정하여 로컬 파일 시스템에 저장
vector_store = Chroma(
    collection_name="complaint_embeddings",
    embedding_function=OpenAIEmbeddings(api_key=settings.OPENAI_API_KEY),
    persist_directory="./chroma_db",
    client=chroma_client if CHROMA_DB_HOST else None
)


# --- 초기 데이터 로드 ---
def initial_load_to_chroma():
    """
    MongoDB의 모든 민원 데이터를 ChromaDB로 로드합니다.
    ChromaDB가 비어 있을 경우에만 실행되어 중복 로드를 방지합니다.
    """
    try:
        # 💡 ChromaDB 컬렉션에 데이터가 있는지 확인
        if vector_store._collection.count() == 0:
            print("ChromaDB가 비어 있습니다. MongoDB에서 기존 민원 데이터를 로드합니다...")
            all_complaints = Complaints.objects()
            documents = []
            for complaint in all_complaints:
                com_type_value = complaint.com_type
                # 💡 com_type이 리스트인 경우 첫 번째 요소만 추출 (ChromaDB 제약사항)
                if isinstance(com_type_value, list) and com_type_value:
                    com_type_value = com_type_value[0]

                doc_to_embed = LangchainDocument(
                    page_content=complaint.com_contents,
                    metadata={
                        "username": complaint.username,
                        "com_id": complaint.com_id,
                        "com_type": com_type_value
                    }
                )
                documents.append(doc_to_embed)

            if documents:
                vector_store.add_documents(documents)
                print(f"MongoDB에서 총 {len(documents)}개의 민원 데이터를 ChromaDB에 로드 완료.")
        else:
            print("ChromaDB에 이미 데이터가 존재하여 초기 로드를 건너뜁니다.")
    except Exception as e:
        logger.error(f"ChromaDB 초기 로드 실패: {e}", exc_info=True)


# 💡 서버 시작 시 함수를 호출하여 초기 데이터 로드
initial_load_to_chroma()


# --- MongoDB 카운터 기반 ID 생성 ---
def get_next_chat_id():
    """
    MongoDB Counter 컬렉션을 사용하여 새로운 채팅 ID(chat_*)를 생성합니다.
    오류 발생 시 UUID 기반의 ID를 반환합니다.
    """
    try:
        counter = Counter.objects(name='chat_id').modify(upsert=True, new=True, inc__seq=1)
        if not counter:
            counter = Counter(name='chat_id', seq=1)
            counter.save()
        return f"chat_{counter.seq}"
    except Exception as e:
        logger.error(f"chat_id 생성 실패: {e}")
        return f"chat_{uuid4()}"


def get_next_session_id():
    """
    MongoDB Counter 컬렉션을 사용하여 새로운 세션 ID(session_*)를 생성합니다.
    오류 발생 시 UUID 기반의 ID를 반환합니다.
    """
    try:
        counter = Counter.objects(name='session_id').modify(upsert=True, new=True, inc__seq=1)
        if not counter:
            counter = Counter(name='session_id', seq=1)
            counter.save()
        return f"session_{counter.seq}"
    except Exception as e:
        logger.error(f"session_id 생성 실패: {e}")
        return f"session_{uuid4()}"


def get_next_file_id():
    """
    MongoDB Counter 컬렉션을 사용하여 새로운 파일 ID(file_*)를 생성합니다.
    오류 발생 시 UUID 기반의 ID를 반환합니다.
    """
    try:
        counter = Counter.objects(name='file_id').modify(upsert=True, new=True, inc__seq=1)
        if not counter:
            counter = Counter(name='file_id', seq=1)
            counter.save()
        return f"file_{counter.seq}"
    except Exception as e:
        logger.error(f"file_id 생성 실패: {e}")
        return f"file_{uuid4()}"


# --- 챗봇 API 엔드포인트 ---
@csrf_exempt
def chatbot_api(request):
    """
    POST 요청을 받아 챗봇 대화를 처리하고 결과를 반환하는 핵심 뷰입니다.
    사용자 메시지, 챗봇 응답, 파일 및 민원 데이터를 MongoDB에 저장합니다.
    """
    print("=== chatbot_api 호출됨 ===")
    logger.warning("chatbot_api 호출됨")
    if request.method != "POST":
        return JsonResponse({'error': 'POST 요청만 허용됩니다.'}, status=405)

    username = request.user.username if getattr(request.user, "is_authenticated", False) else "guest"
    user_input = (request.POST.get('message') or '').strip()
    scenario_id = request.POST.get('scenario_id') or 'default'
    has_file = ('file' in request.FILES) or ('files' in request.FILES)

    if not user_input and not has_file:
        return JsonResponse({'response': '', 'session_id': request.POST.get('session_id') or ''})

    session_id = request.POST.get('session_id')
    if not session_id:
        session_id = get_next_session_id()
        print(f"새 session_id 발급: {session_id}")
    else:
        print(f"기존 session_id 사용: {session_id}")

    print(f"username={username}, input={user_input}, scenario_id={scenario_id}, session_id={session_id}")

    # 💡 요청에서 위치 정보(위도, 경도)를 추출
    lat = float(request.POST.get('lat')) if request.POST.get('lat') not in (None, '',) else None
    lon = float(request.POST.get('lon')) if request.POST.get('lon') not in (None, '',) else None

    # 💡 챗봇 라우터 호출
    try:
        result = chatbot_router(user_input, username, session_id, scenario_id)
        print("router 결과:", result)
    except Exception as e:
        logger.error(f"router 호출 실패: {e}", exc_info=True)
        result = {'response': '챗봇 처리 중 오류가 발생했습니다.', 'session_id': session_id, 'is_final': False}

    # 💡 ChatHistory에 사용자 메시지 저장
    try:
        chat_doc = ChatHistory(
            chat_id=get_next_chat_id(),
            username=username,
            scenario_id=scenario_id,
            session_id=session_id,
            role='user',
            content=user_input,
            latitude=lat,
            longitude=lon,
            is_final=False,
            metadata={},
            created_at=datetime.now()
        )
        chat_doc.save()
        print(f"ChatHistory 저장 완료(user): {chat_doc.chat_id}")
    except Exception as e:
        logger.error(f"ChatHistory(user) 저장 실패: {e}", exc_info=True)

    # 💡 ChatFiles에 업로드된 파일 저장
    try:
        files = []
        if 'file' in request.FILES:
            files = request.FILES.getlist('file')
        elif 'files' in request.FILES:
            files = request.FILES.getlist('files')

        if files:
            for f in files:
                file_id = get_next_file_id()
                f.seek(0)
                binary_data = f.read()
                ChatFiles(
                    file_id=file_id,
                    # ❗️❗️❗️ 수정된 부분: chat_id를 ChatHistory 객체 자체로 설정
                    chat_id=chat_doc,
                    file_name=f.name,
                    file_data=binary_data,
                    file_type=getattr(f, "content_type", ""),
                    uploaded_at=datetime.now()
                ).save()
                print(f"파일 저장 완료: file_id={file_id}")
    except Exception as e:
        logger.error(f"파일 저장 처리 실패: {e}", exc_info=True)

    # 💡 ChatHistory에 챗봇 응답 저장
    try:
        is_final = result.get('is_final', False)
        # ❗️❗️❗️ 수정된 부분: 챗봇 응답에 민원 유형(com_type)을 metadata에 저장
        metadata = {'com_type': result.get('com_type', [])}
        ChatHistory(
            chat_id=get_next_chat_id(),
            username=username,
            scenario_id=scenario_id,
            session_id=session_id,
            role='assistant',
            content=result.get('response', ''),
            is_final=is_final,
            metadata=metadata,  # metadata를 여기서 저장
            created_at=datetime.now()
        ).save()
        print("ChatHistory 저장 완료(bot)")
    except Exception as e:
        logger.error(f"ChatHistory(bot) 저장 실패: {e}", exc_info=True)

    # 💡 민원 자동 생성 및 저장 로직
    try:
        # 💡 is_final 플래그가 True일 때만 민원 저장 시도
        if result.get('is_final', False):
            com_type_from_router = result.get('com_type')

            # 💡 챗봇으로부터 받은 요약본을 사용
            complaint_summary = result.get('summary')

            # 💡 위치 정보는 첫 번째로 위치를 포함한 사용자 메시지에서 가져옴
            location_doc = ChatHistory.objects(session_id=session_id, role='user', latitude__exists=True).order_by(
                'created_at').first()

            if not location_doc or not location_doc.latitude or not location_doc.longitude:
                logger.warning(f"민원(session_id: {session_id}) 저장을 위한 위치 정보가 부족합니다. 민원 저장이 취소됩니다.")
                return JsonResponse({
                    'response': '죄송합니다. 위치 정보가 없어 민원 접수가 어렵습니다. 위치 정보를 포함하여 다시 시도해 주세요.',
                    'session_id': session_id
                })

            lat = location_doc.latitude
            lon = location_doc.longitude

            if com_type_from_router:
                # 💡 com_id를 complaints 컬렉션에서 1000000 이상의 가장 높은 값 + 1로 설정
                latest_chatbot_complaint = Complaints.objects(com_id__gte=1000000).order_by('-com_id').first()
                if latest_chatbot_complaint and isinstance(latest_chatbot_complaint.com_id, int):
                    complaint_id = latest_chatbot_complaint.com_id + 1
                else:
                    complaint_id = 1000000  # 챗봇 민원 데이터가 없을 경우 1000000부터 시작

                com_type_for_db = ', '.join(com_type_from_router) if isinstance(com_type_from_router,
                                                                                list) else com_type_from_router

                complaint_data = {
                    "com_id": complaint_id,
                    "username": username,
                    "com_type": com_type_for_db,
                    "lat": lat,
                    "lon": lon,
                    "com_contents": complaint_summary,  # 챗봇이 요약한 내용으로 저장
                    "com_reg_date": datetime.now()
                }

                # 💡 디버깅 코드 추가: 최종 저장될 com_contents 출력
                print(f"최종 저장될 com_contents: {complaint_data['com_contents']}")

                # 💡 해당 채팅에 첨부된 파일 정보(2개까지) 가져오기
                user_complaints_docs = ChatHistory.objects(session_id=session_id, role='user',
                                                           scenario_id='complain_submit').order_by('created_at')
                related_files = ChatFiles.objects(chat_id__in=[doc.id for doc in user_complaints_docs]).order_by(
                    "-uploaded_at")[:2]

                for i, file in enumerate(related_files):
                    if i == 0:
                        complaint_data["com_pic1"] = file.file_data
                    elif i == 1:
                        complaint_data["com_pic2"] = file.file_data

                # 💡 1. MongoDB에 민원 정보 저장
                Complaints(**complaint_data).save()
                print(f"Complaints 저장 완료: com_id={complaint_id}")

                # 💡 2. 임베딩을 생성하여 ChromaDB에 저장
                doc_to_embed = LangchainDocument(
                    page_content=complaint_summary,  # 요약된 내용을 임베딩
                    metadata={
                        "username": username,
                        "com_id": complaint_id,
                        "com_type": com_type_for_db
                    }
                )
                vector_store.add_documents([doc_to_embed])
                print("ChromaDB에 임베딩 저장 완료")
    except Exception as e:
        logger.error(f"Complaints 및 임베딩 자동 생성 실패: {e}", exc_info=True)
        return JsonResponse({
            'response': '민원 접수 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.',
            'session_id': session_id
        })

    # 💡 최종 응답 반환
    return JsonResponse({
        'response': result.get('response', ''),
        'session_id': session_id
    })


# --- 기타 뷰 ---
@login_required
def chatbot_chat(request, scenario_id):
    """지정된 시나리오 ID의 챗봇 채팅 페이지를 렌더링합니다."""
    return render(request, 'chatbot/chatbot_chat.html', {'scenario_id': scenario_id})


@login_required
def chatbot_chat_default(request):
    """기본 챗봇 채팅 페이지를 렌더링합니다."""
    return render(request, 'chatbot/chatbot_chat_default.html')