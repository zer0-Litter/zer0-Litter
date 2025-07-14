from django.shortcuts import render
from common.models import Users
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import UserRegisterSerializer
from django.shortcuts import redirect
from django.contrib.auth.hashers import check_password
from django.contrib import messages
from rest_framework_simplejwt.tokens import RefreshToken
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
import json
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

        # 로그인 성공 후, 사용자 아이디와 환영 메시지 반환
        return Response({
            "message": f"{username} 님 환영합니다!",
            "username": username,
            "access" : str(refresh.access_token),
            "refresh" : str(refresh)
        }, status=status.HTTP_200_OK)



def login(request):
    return render(request, 'accounts/login.html')

def mypage_home(request):
    return render(request, 'accounts/mypage_home.html')