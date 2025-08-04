from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt

from chatbot.chatbot_core import chatbot_router
from common.models import Users


@csrf_exempt
def chatbot_api(request):
    if request.method == 'POST':
        if not request.user.is_authenticated:
            return JsonResponse({'error': '로그인이 필요합니다.'}, status=401)

        username = request.user.username
        session_id = request.POST.get('session_id')
        scenario_id = request.POST.get('scenario_id', None)
        user_input = request.POST.get('message', '')
        lat = request.POST.get('lat')
        lon = request.POST.get('lon')

        # 필수 입력값 체크
        if not user_input:
            return JsonResponse({'error': '메시지가 비어 있습니다.'}, status=400)
        if not lat or not lon:
            return JsonResponse({'error': '위도 및 경도 정보가 필요합니다.'}, status=400)

        # 사용자 유효성 검사
        try:
            Users.objects.get(username=username)
        except Users.DoesNotExist:
            return JsonResponse({"error": "사용자 정보를 찾을 수 없습니다."}, status=404)

        # 챗봇 응답 생성
        bot_response = chatbot_router(
            user_input,
            username=username,
            session_id=session_id,
            scenario_id=scenario_id,
            lat=lat,
            lon=lon
        )

        return JsonResponse({'response': bot_response})

    return JsonResponse({'error': 'POST 요청만 허용됩니다.'}, status=405)


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
