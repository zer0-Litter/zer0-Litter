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

    # 파일 유무 체크
    has_file = ('file' in request.FILES) or ('files' in request.FILES)

    # ⚠️ 빈 메시지 + 파일 없음이면 아무 것도 안 함(세션 발급 X)
    if not user_input and not has_file:
        return JsonResponse({'response': '', 'session_id': request.POST.get('session_id') or ''})

    # session_id 처리
    session_id = request.POST.get('session_id')
    if not session_id:
        session_id = get_next_session_id()
        print(f"새 session_id 발급: {session_id}")
    else:
        print(f"기존 session_id 사용: {session_id}")

    print(f"username={username}, input={user_input}, scenario_id={scenario_id}, session_id={session_id}")

    # -------- Router 호출 (저장은 라우터가 하지 않도록 위에서 변경) --------
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
            session_id=session_id,  # result의 session_id와 동일
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
                f.seek(0)  # 파일 포인터를 맨 앞으로
                binary_data = f.read()  # 전체 읽기

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
        # com_type, lat, lon 모두 있어야 Complaints 생성
        if chat_doc and chat_doc.latitude and chat_doc.longitude and request.POST.get("com_type"):
            from common.models_mongo import Complaints  # 지연 로딩

            complaint_data = {
                "com_id": Counter.objects(name="complaint").modify(
                    upsert=True, new=True, inc__seq=1
                ).seq,
                "username": username,
                "com_type": request.POST.get("com_type"),
                "lat": chat_doc.latitude,
                "lon": chat_doc.longitude,
                "com_title": user_input or "자동 생성 민원",
                "com_contents": user_input,
                "com_reg_date": datetime.now()
            }

            # 최근 ChatFiles 2개 첨부
            related_files = ChatFiles.objects(chat_id=chat_doc).order_by("-uploaded_at")[:2]
            if related_files:
                if len(related_files) >= 1:
                    complaint_data["com_pic1"] = related_files[0].file_data
                if len(related_files) >= 2:
                    complaint_data["com_pic2"] = related_files[1].file_data

            Complaints(**complaint_data).save()
            print(f"Complaints 저장 완료: com_id={complaint_data['com_id']}")
    except Exception as e:
        logger.error(f"Complaints 자동 생성 실패: {e}", exc_info=True)

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
