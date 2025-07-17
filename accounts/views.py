from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from common.models import Users
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import UserRegisterSerializer
from django.shortcuts import redirect
from django.contrib import messages
from rest_framework_simplejwt.tokens import RefreshToken
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.http import JsonResponse
from django.contrib.auth import login as auth_login
from django.contrib.auth.hashers import check_password
from django.contrib.auth import logout
from django.urls import reverse
import json
import re

# Create your views here.

class RegisterView(APIView):
    def get(self,request):
        # get 요청에 대해 회원가입 폼을 렌더링
        return render(request, 'accounts/register.html')

    def post(self, request):
        # 시리얼라이저에 데이터 전달
        serializer = UserRegisterSerializer(data=request.data)

        # 시리얼라이저가 유효한지 확인
        if serializer.is_valid():
            # 데이터 저장
            user = serializer.save()
            return Response({
                "message": f"{user.username} 가입해주셔서 감사합니다",
                "username": user.username
            }, status=status.HTTP_201_CREATED)

        # 유효하지 않으면 오류 리턴
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@csrf_exempt
def check_user_id(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        username = data.get('username')
        is_taken = Users.objects.filter(username=username).exists()
        return JsonResponse({'is_taken':is_taken})

@csrf_exempt
def check_password_api(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        password = data.get('password')
        user = request.user

        if not user.is_authenticated:
            return JsonResponse({'valid':False})

        is_valid = check_password(password, user.password)
        return JsonResponse({'valid':is_valid})



class LoginView(APIView):
    def post(self, request):
        username = request.POST['username']
        password = request.POST['password']

        try:
            user = Users.objects.get(username=username)
        except Users.DoesNotExist:
            return Response({"message": "존재하지 않는 아이디입니다."}, status=status.HTTP_400_BAD_REQUEST)

        if not check_password(password, user.password):
            return Response({"message": "비밀번호가 일치하지 않습니다."}, status=status.HTTP_400_BAD_REQUEST)

        # 비밀번호가 맞으면 JWT 발급
        refresh = RefreshToken.for_user(user)

        # Django 세션 로그인 수행
        auth_login(request, user)

        # 로그인 성공 후, 사용자 아이디와 환영 메시지 반환
        return Response({
            "message": f"{username} 님 환영합니다!",
            "username": username,
            "access" : str(refresh.access_token),
            "refresh" : str(refresh)
        }, status=status.HTTP_200_OK)



def login(request):
    return render(request, 'accounts/login.html')


def mypage_edit(request): # 회원정보 수정 페이지를 보여줌
    user = request.user
    return render(request, 'accounts/mypage_edit.html', {'user':user})


@csrf_protect
def mypage_update(request):
    # 로그인하지 않은 경우 로그인 페이지로 리다이렉트
    if not request.user.is_authenticated:
        messages.warning(request, '로그인이 필요합니다.')
        return redirect('accounts:login')

    # POST 요청일 때만 수정 처리
    if request.method == 'POST':
        user = request.user
        phone = request.POST.get('phone_number')
        address = request.POST.get('address')
        current_pw = request.POST.get('current_password')
        new_pw = request.POST.get('password')
        new_pw_confirm = request.POST.get('password_confirm')

        # 현재 비밀번호 검증
        if not check_password(current_pw, user.password):
            messages.error(request, '현재 비밀번호가 일치하지 않습니다.')
            return redirect('accounts:mypage_edit')

        # 비밀번호 변경 요청이 있을 경우
        if new_pw:
            regex = r'^(?=.*[a-z])(?=.*\d)(?=.*[@$!%*#?&]).{8,}$'

            # 비밀번호 유효성 검사
            if not re.match(regex, new_pw):
                messages.error(request, '새 비밀번호는 소문자, 숫자, 특수문자를 포함하여 8자 이상이어야 합니다.')
                return redirect('accounts:mypage_edit')

            # 비밀번호 확인 검사
            if new_pw != new_pw_confirm:
                messages.error(request, '새 비밀번호와 비밀번호 확인이 일치하지 않습니다.')
                return redirect('accounts:mypage_edit')

            if check_password(new_pw, user.password):
                messages.error(request, '새 비밀번호는 현재 비밀번호와 달라야 합니다.')
                return redirect('accounts:mypage_edit')

            user.set_password(new_pw) # 비밀번호가 해싱되어 저장

        # 정보 저장
        user.phone_number = phone
        user.address = address
        user.save()

        messages.success(request, '회원정보가 수정되었습니다.')
        return redirect('accounts:mypage_home')

    # GET 요청 등은 수정 폼 페이지로 다시 보여주기
    return redirect('accounts:mypage_edit')

@csrf_protect
@login_required
def delete_user(request):
    if request.method == 'POST':
        user = request.user
        logout(request)     # 세션에서 로그아웃
        user.delete()       # DB에서 계정 삭제
        messages.success(request, '계정이 성공적으로 삭제되었습니다.')
        return redirect(reverse('accounts:login_view') + '?status=deleted')  # 로그인 페이지로 이동
    else:
        return redirect('accounts:mypage_home')  # POST 아닌 경우 마이페이지로


def mypage_home(request):
    return render(request, 'accounts/mypage_home.html')