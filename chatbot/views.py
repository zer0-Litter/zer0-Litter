from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt

from chatbot.chatbot_core import chatbot_router, save_chat_history, generate_session_id
from common.models import Users


@csrf_exempt
def chatbot_api(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST 요청만 허용됩니다.'}, status=405)

    if not request.user.is_authenticated:
        return JsonResponse({'error': '로그인이 필요합니다.'}, status=401)

    try:
        username = request.user.username
        user_input = request.POST.get('message', '').strip()
        scenario_id = request.POST.get('scenario_id', 'greeting')
        session_id = request.POST.get('session_id', '') or generate_session_id()

        lat = request.POST.get('lat')
        lon = request.POST.get('lon')

        if lat and lon:
            try:
                user_location = {
                    'lat': float(lat),
                    'lng': float(lon)
                }
            except ValueError:
                user_location = None
        else:
            user_location = None

        # 사용자 입력 저장 (user role)
        save_chat_history(username, scenario_id, session_id, "user", user_input, location=user_location)

        # LangChain 처리
        ai_response = chatbot_router(
            scenario_id=scenario_id,
            user_input=user_input,
            session_id=session_id,
            username=username,
            location=user_location
        )

        # AI 응답 저장 (assistant role)
        save_chat_history(username, scenario_id, session_id, "assistant", ai_response, location=None)

        return JsonResponse({
            'message': ai_response,
            'session_id': session_id,
            'location': user_location,
        })

    except Exception as e:
        return JsonResponse({'error': f'서버 오류: {str(e)}'}, status=500)

@login_required(login_url='accounts:login')  # 로그인 안 된 경우 login_url로 리다이렉트
def chatbot_chat(request, scenario_id):
    if request.method == 'POST':
        user_message = request.POST.get('message')
        # 여기서 챗봇 응답 처리 로직 작성
        # 더미 응답 처리
        bot_response = "이건 더미 응답이에요."
        return render(request, 'chatbot/chatbot_chat.html', {
            'user_message': user_message,
            'bot_response': bot_response,
            'scenario_id': scenario_id
        })
    return render(request, 'chatbot/chatbot_chat.html', {'scenario_id': scenario_id})

@login_required(login_url='accounts:login')
def chatbot_chat_default(request):
    return render(request, 'chatbot/chatbot_chat_default.html')
