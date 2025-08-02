from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt

from chatbot.chatbot_core import chatbot_router


def chatbot_chat_default(request):
    # 시나리오 ID 없이 접속하는 기본 챗봇 페이지
    return render(request, 'chatbot/chatbot_chat_default.html')

@csrf_exempt
def chatbot_api(request):
    if request.method == 'POST':
        user_input = request.POST.get('message', '')
        username = request.POST.get('username', 'web_user')  # username 기본값 설정
        session_id = request.POST.get('session_id', None)
        scenario_id = request.POST.get('scenario_id', None)

        # 내부 함수는 user_id 인자로 username을 넘겨줌
        bot_response = chatbot_router(user_input, user_id=username, session_id=session_id, scenario_id=scenario_id)
        return JsonResponse({'response': bot_response})
    return JsonResponse({'error': 'Invalid request'}, status=400)


def chatbot_chat(request, scenario_id):
    if request.method == 'POST':
        user_message = request.POST.get('message')
        # 더미 응답 처리
        bot_response = "이건 더미 응답이에요."
        return render(request, 'chatbot/chatbot_chat.html', {
            'user_message': user_message,
            'bot_response': bot_response,
            'scenario_id': scenario_id
        })
    return render(request, 'chatbot/chatbot_chat.html', {'scenario_id': scenario_id})
