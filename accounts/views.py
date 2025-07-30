from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_GET
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
from django.contrib.auth import login as auth_login, update_session_auth_hash
from django.contrib.auth.hashers import check_password
from django.contrib.auth import logout
import json
import re
from common.models_mongo import Complaints, ComplaintStatus
from bson import ObjectId
from django.contrib.auth import logout as django_logout



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

@require_GET
def logout_view(request):
    django_logout(request)
    return redirect('accounts:login')

def mypage_edit(request): # 회원정보 수정 페이지를 보여줌
    user = request.user
    return render(request, 'accounts/mypage_edit.html', {'user':user})


@csrf_protect
def mypage_update(request):
    if not request.user.is_authenticated:
        messages.warning(request, '로그인이 필요합니다.')
        return redirect('accounts:login')

    if request.method != 'POST':
        return redirect('accounts:mypage_edit')

    user     = request.user
    phone    = request.POST.get('phone_number')
    address  = request.POST.get('address')
    current  = request.POST.get('current_password')
    new_pw   = request.POST.get('password')
    confirm  = request.POST.get('password_confirm')

    # 새 비밀번호가 입력된 경우에만 현재 비밀번호 확인
    if new_pw:
        if not user.check_password(current):
            messages.error(request, '현재 비밀번호가 일치하지 않습니다.')
            return redirect('accounts:mypage_edit')

    # 비밀번호 변경 요청이 있을 때
    if new_pw:
        user.set_password(new_pw)
        user.phone_number = phone
        user.address = address
        user.save()

        django_logout(request)
        response = redirect('accounts:mypage_edit')
        response.set_cookie('show_password_changed_modal', '1', max_age=10)
        return response

    # 일반 정보만 수정하는 경우
    modified = False

    if user.phone_number != phone:
        user.phone_number = phone
        modified = True

    if user.address != address:
        user.address = address
        modified = True

    if modified:
        user.save()
        update_session_auth_hash(request, user)
        messages.success(request, '회원정보가 수정되었습니다.')
    else:
        messages.info(request, '변경된 정보가 없습니다.')

    return redirect('accounts:mypage_home')

@csrf_protect
@login_required
def delete_user(request):
    if request.method == 'POST':
        user = request.user
        logout(request)     # 세션에서 로그아웃
        user.delete()       # DB에서 계정 삭제

        # 로그인 페이지로 리디렉트하면서 쿠키 설정
        response = redirect('accounts:login')
        response.set_cookie('show_account_deleted_modal', '1', max_age=10)
        return response

    else:
        return redirect('accounts:mypage_home')  # POST 아닌 경우 마이페이지로

def login_required_with_modal(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            # 로그인 필요 모달용 쿠키를 세팅한 뒤 리다이렉트
            response = redirect('accounts:login')
            response.set_cookie('show_login_required_modal', '1', max_age=10)
            return response
        return view_func(request, *args, **kwargs)
    return _wrapped_view



@require_GET
@login_required_with_modal
def mypage_home(request):
    username = request.user.username
    user_complaints = Complaints.objects(user_id=username).order_by('-com_reg_date')

    total_count = user_complaints.count()
    complete_count = 0
    processing_count = 0

    for complaint in user_complaints:
        try:
            status = ComplaintStatus.objects(status_id=ObjectId(complaint.status_id)).first()
            name = status.status_name if status else '처리중'
        except Exception:
            name = '처리중'

        if name == '완료':
            complete_count += 1
        else:
            processing_count += 1

    recent_complaints = user_complaints[:3]
    complaints_display = []

    for complaint in recent_complaints:
        try:
            status = ComplaintStatus.objects(status_id=ObjectId(complaint.status_id)).first()
            status_name = status.status_name if status else '처리중'
        except Exception:
            status_name = '처리중'

        complaint_type = complaint.com_type
        if isinstance(complaint_type, list):
            icon_type = complaint_type[0]
        else:
            icon_type = complaint_type.split(',')[0].strip()

        complaints_display.append({
            'title': complaint.com_title,
            'date': complaint.com_reg_date,
            'type': complaint_type,
            'location': complaint.com_location,
            'status': status_name,
            'icon_type': icon_type
        })

    return render(request, 'accounts/mypage_home.html', {
        'complaints': complaints_display,
        'total_count': total_count,
        'complete_count': complete_count,
        'processing_count': processing_count,
    })


@login_required
def complaint_all_list(request):
    username = request.user.username
    user_complaints = Complaints.objects(user_id=username).order_by('-com_reg_date')

    all_complaints = []
    for complaint in user_complaints:
        try:
            status = ComplaintStatus.objects(status_id=ObjectId(complaint.status_id)).first()
            status_name = status.status_name if status else '처리중'
        except Exception:
            status_name = '처리중'

        all_complaints.append({
            'title': complaint.com_title,
            'date': complaint.com_reg_date,
            'type': complaint.com_type,
            'location': complaint.com_location,
            'status': status_name
        })

    return render(request, 'accounts/complaint_all_list.html', {
        'complaints': all_complaints
    })