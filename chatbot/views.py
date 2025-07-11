from django.shortcuts import render, redirect

# Create your views here.
def chatbot_modal(request):
    # 챗봇 모달 페이지 렌더링
    return render(request, 'chatbot/chatbot_modal.html')

def chatbot_chat(request, scenario_id):
    # 챗봇 채팅 페이지 렌더링
    context = {'scenario_id': scenario_id}
    return render(request, 'chatbot/chatbot_chat.html', context)

def chatbot_chat_default(request):
    # 시나리오 ID 없이 접속하는 기본 챗봇 페이지
    return render(request, 'chatbot/chatbot_chat_default.html')

def complain_chatbot(request, scenario_id):
    # 챗봇 민원 접수 후 리다이렉트(임시)
    return redirect('/complain/complain_add/')
