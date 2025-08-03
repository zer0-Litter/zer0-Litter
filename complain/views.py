from django.shortcuts import render
from django.contrib.auth.decorators import login_required

@login_required(login_url='accounts:login')
def complain_add(request):
    return render(request, 'complain/complain_add.html')  # 템플릿 경로 맞게 수정
