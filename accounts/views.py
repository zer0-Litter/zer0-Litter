from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils.decorators import method_decorator
from rest_framework.parsers import MultiPartParser,FormParser
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
import json
import re
from common.models_mongo import Complaints, ComplaintStatus



# Create your views here.

@method_decorator(csrf_exempt, name='dispatch')
class RegisterView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        return render(request, 'accounts/register.html')

    def post(self, request):
        # FormData이므로 request.data를 그대로 쓰면 오류 발생 가능 → request.POST로 받음
        serializer = UserRegisterSerializer(data=request.POST)

        if serializer.is_valid():
            user = serializer.save()
            return JsonResponse({"username": user.username}, status=201)

        return JsonResponse(serializer.errors, status=400)

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

        # 로그인 성공 후, 최소 데이터만 반환
        return Response({
            "username": username,
            "access": str(refresh.access_token),
            "refresh": str(refresh)
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
        return redirect('accounts:login')  # HTML 로그인 폼 뷰로 이동
    else:
        return redirect('accounts:mypage_home')  # POST 아닌 경우 마이페이지로


@login_required
def mypage_home(request):
    username = request.user.username

    # 로그인한 유저의 민원 리스트 가져오기
    user_complaints = Complaints.objects(user_id=username).order_by('-com_reg_date')

    # 각 민원에 대응하는 상태 이름을 붙여줌
    complaint_list = []
    for complaint in user_complaints:
        status = ComplaintStatus.objects(status_id=str(complaint.status_id)).first()
        complaint_list.append({
            'title': complaint.com_title,
            'date': complaint.com_reg_date,
            'type': complaint.com_type,
            'location': complaint.com_location,
            'status': status.status_name if status else '알 수 없음'
        })

    return render(request, 'mypage_home.html', {
        'complaints': complaint_list
    })