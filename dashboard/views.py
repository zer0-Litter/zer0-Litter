from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

@login_required(login_url='accounts:login')
def dashboard(request):
    return render(request, 'dashboard/dashboard.html')  # 템플릿 경로 맞게 수정
