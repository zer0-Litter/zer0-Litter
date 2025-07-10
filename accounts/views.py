from django.shortcuts import render, redirect

# Create your views here.
def register(request):
    # 회원가입 페이지 렌더링
    return render(request, 'accounts/register.html')

def login(request):
    # 로그인 페이지 렌더링
    return render(request, 'accounts/login.html')

def logout(request):
    # 로그아웃 후 로그인 페이지로 리다이렉트
    return redirect('trash_loc/home.html')

