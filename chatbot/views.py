
from django.shortcuts import render, redirect


# Create your views here.
# def chatbot_chat(request, scenario_id):
#     context = {'scenario_id': scenario_id}
#     return render(request, 'chatbot/chatbot_chat.html', context)

def chatbot_chat_default(request):
    # 시나리오 ID 없이 접속하는 기본 챗봇 페이지
    return render(request, 'chatbot/chatbot_chat_default.html')

from django.shortcuts import render

def chatbot_chat(request, scenario_id):
    if request.method == 'POST':
        user_message = request.POST.get('message')
        # 여기서 챗봇 응답 처리 로직을 넣을 수 있어
        bot_response = "이건 더미 응답이에요."
        return render(request, 'chatbot/chatbot_chat.html', {
            'user_message': user_message,
            'bot_response': bot_response,
            'scenario_id': scenario_id
        })
    return render(request, 'chatbot/chatbot_chat.html', {'scenario_id': scenario_id})
