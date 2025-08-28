from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from .chatbot_core import chatbot_router
from common.models_mongo import ChatHistory, Counter, ChatFiles  # ChatFiles 추가
from datetime import datetime
import logging, os
from uuid import uuid4

logger = logging.getLogger(__name__)

# ---------------- Counter 기반 ID 생성 ----------------
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

# ---------------- file_id 생성기 ----------------
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

def _ensure_upload_dir(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)

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

    # session_id 처리
    session_id = request.POST.get('session_id')
    if not session_id:
        session_id = get_next_session_id()
        print(f"새 session_id 발급: {session_id}")
    else:
        print(f"기존 session_id 사용: {session_id}")

    print(f"username={username}, input={user_input}, scenario_id={scenario_id}, session_id={session_id}")

    # ---------------- router 호출 ----------------
    try:
        result = chatbot_router(user_input, username, session_id, scenario_id)
        print("router 결과:", result)
    except Exception as e:
        logger.error(f"router 호출 실패: {e}", exc_info=True)
        result = {'response': '챗봇 처리 중 오류가 발생했습니다.', 'session_id': session_id}

    # ---------------- chat 기록 저장 ----------------
    chat_doc = None
    chat_id_str = get_next_chat_id()
    try:
        lat = float(request.POST.get('lat')) if request.POST.get('lat') not in (None, '',) else None
        lon = float(request.POST.get('lon')) if request.POST.get('lon') not in (None, '',) else None

        # ChatHistory에 user 메시지 저장
        chat_doc = ChatHistory(
            chat_id=chat_id_str,
            username=username,
            scenario_id=scenario_id,
            session_id=result.get('session_id', session_id),
            role='user',
            content=user_input,
            latitude=lat,
            longitude=lon,
            is_final=False,
            metadata={},
            created_at=datetime.now()
        )
        chat_doc.save()
        print(f"ChatHistory 저장 완료: chat_id={chat_id_str}")
    except Exception as e:
        logger.error(f"ChatHistory 저장 실패: {e}", exc_info=True)

    # ---------------- bot 응답 ChatHistory 저장 ----------------
    try:
        bot_chat_id = get_next_chat_id()
        ChatHistory(
            chat_id=bot_chat_id,
            username=username,
            scenario_id=scenario_id,
            session_id=session_id,
            role='assistant',
            content=result.get('response', ''),
            is_final=False,
            created_at=datetime.now()
        ).save()
    except Exception as e:
        logger.error(f"Bot ChatHistory 저장 실패: {e}", exc_info=True)

    # ---------------- 파일 저장 처리 ----------------
    try:
        if 'file' in request.FILES:
            files = request.FILES.getlist('file')
            upload_root = "uploads"
            for f in files:
                file_id = get_next_file_id()
                saved_path = os.path.join(upload_root, f"{file_id}_{f.name}")
                _ensure_upload_dir(saved_path)

                with open(saved_path, 'wb+') as dest:
                    for chunk in f.chunks():
                        dest.write(chunk)

                ChatFiles(
                    file_id=file_id,
                    chat_id=chat_doc,  # user 메시지 참조
                    file_name=f.name,
                    file_path=saved_path,
                    file_type=f.content_type,
                    uploaded_at=datetime.now()
                ).save()
                print(f"파일 저장 완료: file_id={file_id}, path={saved_path}")
    except Exception as e:
        logger.error(f"파일 저장 처리 실패: {e}", exc_info=True)

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
