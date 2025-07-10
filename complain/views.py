from django.shortcuts import render

# Create your views here.
def complain_trash(request, bin_id):
    # 쓰레기통 민원 페이지 렌더링
    return render(request, 'complain/complain_trash.html', {'bin_id': bin_id})

def complain_add(request):
    # 민원 등록 페이지 렌더링
    return render(request, 'complain/complain_add.html')

def complain_chatbot(request, scenario_id):
    # 챗봇 민원 접수 페이지 렌더링
    return render(request, 'complain/complain_chatbot.html', {'scenario_id': scenario_id})

def complaint_list(request):
    # 내 민원 내역 및 재민원 보기
    return render(request, 'mypage/complaints.html')