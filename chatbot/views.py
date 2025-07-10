from django.shortcuts import render, redirect

# Create your views here.
def chatbot_modal(request):
    # 챗봇 모달 페이지 렌더링
    return render(request, 'chatbot/chatbot_modal.html')

def chatbot_chat(request, scenario_id):
    # 챗봇 채팅 페이지 렌더링
    return render(request, 'chatbot/chatbot_chat.html', {'scenario_id': scenario_id})

def complain_chatbot(request, scenario_id):
    # 챗봇 민원 접수 후 리다이렉트(임시)
    return redirect('/complain/complain_add/')