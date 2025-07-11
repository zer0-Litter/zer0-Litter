
from django.shortcuts import render, redirect


# Create your views here.
def chatbot_chat(request, scenario_id):
    context = {'scenario_id': scenario_id}
    return render(request, 'chatbot/chatbot_chat.html', context)

def chatbot_chat_default(request):
    # 시나리오 ID 없이 접속하는 기본 챗봇 페이지
    return render(request, 'chatbot/chatbot_chat_default.html')