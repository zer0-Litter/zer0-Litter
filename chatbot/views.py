from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from .chatbot_core import chatbot_router
from common.models_mongo import ChatHistory, Counter
from datetime import datetime
import logging
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

# ---------------- chatbot_api ----------------
@csrf_exempt
def chatbot_api(request):
    print("=== chatbot_api 호출됨 ===")
    logger.warning("chatbot_api 호출됨")
    print("method:", request.method)
    print("POST data:", request.POST)

    if request.method != "POST":
        return JsonResponse({'error': 'POST 요청만 허용됩니다.'}, status=405)

    username = request.user.username if request.user.is_authenticated else "guest"
    user_input = request.POST.get('message', '').strip()
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
        logger.error(f"router 호출 실패: {e}")
        result = {'response': '챗봇 처리 중 오류가 발생했습니다.', 'session_id': session_id}

    # ---------------- chat 기록 저장 ----------------
    chat_id = get_next_chat_id()
    try:
        ChatHistory(
            chat_id=chat_id,
            username=username,
            scenario_id=scenario_id,
            session_id=result.get('session_id', session_id),
            role='user',
            content=user_input,
            latitude=float(request.POST.get('lat', 0)),
            longitude=float(request.POST.get('lon', 0)),
            is_final=False,
            metadata={},
            created_at=datetime.now()
        ).save()
        print(f"ChatHistory 저장 완료: chat_id={chat_id}")
    except Exception as e:
        logger.error(f"ChatHistory 저장 실패: {e}")
        print(f"ChatHistory 저장 실패: {e}")

    # ---------------- 응답 반환 ----------------
    try:
        return JsonResponse({
            'response': result.get('response', ''),
            'session_id': result.get('session_id', session_id)
        })
    except Exception as e:
        logger.error(f"JsonResponse 생성 실패: {e}")
        return JsonResponse({'error': '응답 생성 중 오류 발생'}, status=500)

# ---------------- 기존 view 유지 ----------------
@login_required
def chatbot_chat(request, scenario_id):
    return render(request, 'chatbot/chatbot_chat.html', {'scenario_id': scenario_id})

@login_required
def chatbot_chat_default(request):
    return render(request, 'chatbot/chatbot_chat_default.html')
