from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

@login_required(login_url='accounts:login')  # 로그인 안 된 경우 login_url로 리다이렉트
def chatbot_chat(request, scenario_id):
    if request.method == 'POST':
        user_message = request.POST.get('message')
        # 여기서 챗봇 응답 처리 로직 작성
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
