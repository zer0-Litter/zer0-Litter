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


# 💡 최신 LangChain 패키지에서 올바르게 임포트합니다.
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain.docstore.document import Document as LangchainDocument
# 💡 [수정] LangChain 1.0.0 이후 버전에서는 LLMChain이 deprecated 되었습니다.
#    아래 경고가 표시될 경우 chatbot_core.py에서 수정이 필요합니다.
from langchain.chains import LLMChain

logger = logging.getLogger(__name__)

# 💡 .env 파일에서 환경 변수를 로드합니다.
load_dotenv()

# 💡 .env에서 ChromaDB 호스트 IP를 가져옵니다.
CHROMA_DB_HOST = os.getenv("CHROMA_DB_HOST")


# 💡 **[핵심 수정]** ChromaDB가 로컬에서 실행 중이 아닌 경우에만 클라이언트를 임포트합니다.
#    로컬에서는 기본 설정으로 충분합니다.
if CHROMA_DB_HOST:
    from chromadb import HttpClient
    chroma_client = HttpClient(host=CHROMA_DB_HOST, port=8000)
else:
    chroma_client = None


# 💡 생성한 클라이언트를 vector_store에 전달합니다.
#    `client_settings` 대신 `client`를 사용하는 것이 최신 버전의 올바른 방식입니다.
vector_store = Chroma(
    collection_name="complaint_embeddings",
    embedding_function=OpenAIEmbeddings(api_key=settings.OPENAI_API_KEY),
    persist_directory="./chroma_db",
    client=chroma_client if CHROMA_DB_HOST else None
)


# 💡 새로운 함수: 기존 민원 데이터를 ChromaDB에 로드
def initial_load_to_chroma():
    """MongoDB의 모든 민원 데이터를 ChromaDB로 로드합니다."""

    # ChromaDB가 비어 있는지 확인합니다.
    try:
        if vector_store._collection.count() == 0:
            print("ChromaDB가 비어 있습니다. MongoDB에서 기존 민원 데이터를 로드합니다...")
            all_complaints = Complaints.objects()
            documents = []
            for complaint in all_complaints:
                # 💡 **[핵심 수정]** `com_type` 필드의 값이 리스트인지 확인하고,
                #    리스트일 경우 첫 번째 요소만 추출하여 문자열로 변환합니다.
                #    ChromaDB는 metadata 값으로 리스트를 허용하지 않습니다.
                com_type_value = complaint.com_type
                if isinstance(com_type_value, list) and com_type_value:
                    com_type_value = com_type_value[0]

                doc_to_embed = LangchainDocument(
                    page_content=complaint.com_contents,
                    metadata={
                        "username": complaint.username,
                        "com_id": complaint.com_id,
                        "com_type": com_type_value  # 💡 수정된 값을 사용
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

# 💡 서버 시작 시점에 함수를 호출하여 초기 데이터를 로드합니다.
initial_load_to_chroma()


# -------- Counter 기반 ID 생성 --------
def get_next_chat_id():
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
    try:
        counter = Counter.objects(name='file_id').modify(upsert=True, new=True, inc__seq=1)
        if not counter:
            counter = Counter(name='file_id', seq=1)
            counter.save()
        return f"file_{counter.seq}"
    except Exception as e:
        logger.error(f"file_id 생성 실패: {e}")
        return f"file_{uuid4()}"


def get_next_chatbot_com_id():
    try:
        counter = Counter.objects(name='chatbot_com_id').modify(
            upsert=True, new=True, inc__seq=1
        )
        if not counter:
            counter = Counter(name='chatbot_com_id', seq=1)
            counter.save()
            next_seq = 1
        else:
            next_seq = counter.seq

        # 💡 1,000,000을 더해 메인 시스템과 ID 충돌을 방지합니다.
        return 1000000 + next_seq
    except Exception as e:
        logger.error(f"chatbot_com_id 생성 실패: {e}")
        # 실패 시 900000000부터 시작하는 임의의 큰 정수 ID를 반환
        return 900000000 + int(uuid4().int % 1000000)


# ---------------- chatbot_api ----------------
@csrf_exempt
def chatbot_api(request):
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

    # -------- Router 호출 --------
    try:
        result = chatbot_router(user_input, username, session_id, scenario_id)
        print("router 결과:", result)
    except Exception as e:
        logger.error(f"router 호출 실패: {e}", exc_info=True)
        result = {'response': '챗봇 처리 중 오류가 발생했습니다.', 'session_id': session_id}

    # -------- ChatHistory: user 메시지 1회 저장 --------
    chat_doc = None
    try:
        lat = float(request.POST.get('lat')) if request.POST.get('lat') not in (None, '',) else None
        lon = float(request.POST.get('lon')) if request.POST.get('lon') not in (None, '',) else None

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

    # -------- 파일 저장 (ChatFiles 컬렉션) --------
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
                    chat_id=chat_doc,
                    file_name=f.name,
                    file_data=binary_data,
                    file_type=getattr(f, "content_type", ""),
                    uploaded_at=datetime.now()
                ).save()
                print(f"파일 저장 완료: file_id={file_id}")

    except Exception as e:
        logger.error(f"파일 저장 처리 실패: {e}", exc_info=True)

    # -------- ChatHistory: bot 응답 1회 저장 --------
    try:
        ChatHistory(
            chat_id=get_next_chat_id(),
            username=username,
            scenario_id=scenario_id,
            session_id=session_id,
            role='assistant',
            content=result.get('response', ''),
            is_final=False,
            created_at=datetime.now()
        ).save()
        print("ChatHistory 저장 완료(bot)")
    except Exception as e:
        logger.error(f"ChatHistory(bot) 저장 실패: {e}", exc_info=True)

    # -------- Complaints 자동 생성 --------
    try:
        com_type_from_router = result.get('com_type')

        if chat_doc and chat_doc.latitude and chat_doc.longitude and com_type_from_router:
            from common.models_mongo import Complaints

            complaint_id = get_next_chatbot_com_id()

            complaint_data = {
                "com_id": complaint_id,
                "username": username,
                "com_type": com_type_from_router,
                "lat": chat_doc.latitude,
                "lon": chat_doc.longitude,
                "com_contents": user_input,
                "com_reg_date": datetime.now()
            }

            related_files = ChatFiles.objects(chat_id=chat_doc).order_by("-uploaded_at")[:2]

            for i, file in enumerate(related_files):
                if i == 0:
                    complaint_data["com_pic1"] = file.file_data
                elif i == 1:
                    complaint_data["com_pic2"] = file.file_data

            # 💡 1. MongoDB에 민원 정보 저장
            Complaints(**complaint_data).save()
            print(f"Complaints 저장 완료: com_id={complaint_id}")

            # 💡 2. 임베딩을 생성하여 ChromaDB에 저장
            # 메타데이터를 포함하여 나중에 검색 결과 필터링에 활용할 수 있게 함
            doc_to_embed = LangchainDocument(
                page_content=user_input,
                metadata={
                    "username": username,
                    "com_id": complaint_id,
                    "com_type": com_type_from_router
                }
            )
            vector_store.add_documents([doc_to_embed])
            print("ChromaDB에 임베딩 저장 완료")

    except Exception as e:
        logger.error(f"Complaints 및 임베딩 자동 생성 실패: {e}", exc_info=True)

    return JsonResponse({
        'response': result.get('response', ''),
        'session_id': session_id
    })


# ---------------- 기존 view 유지 ----------------
@login_required
def chatbot_chat(request, scenario_id):
    return render(request, 'chatbot/chatbot_chat.html', {'scenario_id': scenario_id})


@login_required
def chatbot_chat_default(request):
    return render(request, 'chatbot/chatbot_chat_default.html')