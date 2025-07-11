
from django.shortcuts import render

# Create your views here.
def login(request):
    return render(request, 'accounts/login.html')

def mypage_home(request):
    return render(request, 'accounts/mypage_home.html')