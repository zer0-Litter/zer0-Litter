from django.http import JsonResponse
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
import logging

from .chatbot_core import chatbot_router

logger = logging.getLogger(__name__)

@csrf_exempt
def chatbot_api(request):
    print("=== chatbot_api 호출됨 ===")
    logger.warning("chatbot_api 호출됨")
    print("method:", request.method)
    print("POST data:", request.POST)

    if request.method != "POST":
        print("POST가 아님")
        return JsonResponse({'error': 'POST 요청만 허용됩니다.'}, status=405)

    username = request.user.username if request.user.is_authenticated else "guest"
    user_input = request.POST.get('message', '').strip()
    scenario_id = request.POST.get('scenario_id')
    session_id = request.POST.get('session_id') or None

    print(f"username={username}, input={user_input}, scenario_id={scenario_id}, session_id={session_id}")

    # router 호출
    result = chatbot_router(user_input, username, session_id, scenario_id)
    print("router 결과:", result)

    return JsonResponse({
        'response': result.get('response', ''),
        'session_id': result.get('session_id', session_id or "generated-in-router")
    })


# --------------------------
# 기존 view 함수도 반드시 유지
# --------------------------

@login_required
def chatbot_chat(request, scenario_id):
    return render(request, 'chatbot/chatbot_chat.html', {'scenario_id': scenario_id})

@login_required
def chatbot_chat_default(request):
    return render(request, 'chatbot/chatbot_chat_default.html')
