from functools import wraps
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_GET, require_POST
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
import re
from common.models_mongo import Complaints, ComplaintStatus
from django.contrib.auth import logout as django_logout
from django.urls import reverse
from django.core.paginator import Paginator
from mongoengine.queryset.visitor import Q
from datetime import datetime, timedelta
import json
from mongoengine.errors import ValidationError, DoesNotExist


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

        # 스태프면 관리자용(스태프) 페이지로, 아니면 trash_loc 홈으로
        target = reverse('complain:pending_list') if user.is_staff else reverse('trash_loc:home')

        return Response({
            "username": username,
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "redirect": target,  # ← 프런트에서 이 값으로 window.location.href 이동
            "is_staff": bool(user.is_staff)  # (옵션) 프런트 분기용
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


def is_valid_password(password):
    if len(password) < 8:
        return False
    if not re.search(r'[0-9]', password):
        return False
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False
    return True


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
    # 비밀번호 변경 요청이 있을 때
    if new_pw:
        if not user.check_password(current):
            messages.error(request, '현재 비밀번호가 일치하지 않습니다.')
            return redirect('accounts:mypage_edit')

        if not is_valid_password(new_pw):
            messages.error(request, '비밀번호는 8자리 이상이며 숫자와 특수문자를 포함해야 합니다.')
            return redirect('accounts:mypage_edit')

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
    user_complaints = Complaints.objects(username=username).order_by('-com_reg_date')

    total_count = user_complaints.count()
    complete_count = 0
    processing_count = 0

    for complaint in user_complaints:
        last = ComplaintStatus.objects(com_id=complaint.com_id) \
            .order_by('-updated_at', '-status_id').first()
        name = last.status_name if last else '처리중'

        if name == '처리완료':
            complete_count += 1
        else:
            processing_count += 1

    recent_complaints = user_complaints[:3]
    complaints_display = []

    for complaint in recent_complaints:
        last = ComplaintStatus.objects(com_id=complaint.com_id) \
            .order_by('-updated_at', '-status_id').first()
        status_name = last.status_name if last else '처리중'

        complaint_type = complaint.com_type
        if isinstance(complaint_type, list):
            icon_type = complaint_type[0]  # 전체 문자열
        else:
            icon_type = complaint_type.split(',')[0].strip()

        complaints_display.append({
            'date': complaint.com_reg_date,
            'type': complaint_type,  # 여기도 전체 리스트/문자열 그대로
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

    q = (request.GET.get('q') or '').strip()
    status = (request.GET.get('status') or '').strip()
    d_from = (request.GET.get('from') or '').strip()
    d_to = (request.GET.get('to') or '').strip()

    base_q = Q(username=username)
    if q:
        base_q &= (
            Q(com_contents__icontains=q) |
            Q(com_location__icontains=q) |
            Q(com_type__icontains=q) |
            Q(com_type__in=[q])  # 리스트형 보완(선택)
        )

    def parse_date(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            return None

    gte, lte = parse_date(d_from), parse_date(d_to)
    if gte and lte and gte > lte:
        gte, lte = lte, gte

    if gte:
        base_q &= Q(com_reg_date__gte=gte)
    if lte:
        base_q &= Q(com_reg_date__lt=lte + timedelta(days=1))  # 종료일 포함

    user_complaints = (
        Complaints.objects(base_q)
        .only('com_id','com_reg_date','com_type','com_location','com_contents')
        .order_by('-com_reg_date')
    )

    all_complaints = []
    for complaint in user_complaints:
        last = (ComplaintStatus.objects(com_id=complaint.com_id)
                .only('status_name','updated_at','status_id')
                .order_by('-updated_at','-status_id')
                .first())
        status_name = last.status_name if last else '처리중'

        raw_type = complaint.com_type
        if isinstance(raw_type, list):
            type_list = [t.strip() for t in raw_type if t and str(t).strip()]
        else:
            type_list = [t.strip() for t in str(raw_type).split(',') if t.strip()]

        type_display = ', '.join(type_list) if type_list else ''
        icon_type = type_list[0] if type_list else '기타'

        all_complaints.append({
            'com_id': complaint.com_id,
            'date': complaint.com_reg_date,
            'type_list': type_list,
            'type_display': type_display,
            'icon_type': icon_type,
            'location': complaint.com_location,
            'status': status_name,
            'content': complaint.com_contents,
        })

    if status in ('처리중','처리완료'):
        all_complaints = [c for c in all_complaints if c['status'] == status]

    paginator = Paginator(all_complaints, 5)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'accounts/complaint_all_list.html', {
        'page_obj': page_obj,
        'query': {'q': q, 'status': status, 'from': d_from, 'to': d_to}
    })

@csrf_exempt
@login_required
@require_POST
def complaint_update_api(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "msg": "잘못된 요청 본문"}, status=400)

    com_id     = data.get("com_id")
    title      = (data.get("title") or "").strip()
    content    = (data.get("content") or "").strip()
    location   = (data.get("location") or "").strip()

    # 유형은 리스트 또는 콤마문자열 모두 허용
    raw_type = data.get("type_list") or data.get("type_display")
    if isinstance(raw_type, str):
        type_list = [t.strip() for t in raw_type.split(",") if t.strip()]
    else:
        type_list = [t.strip() for t in (raw_type or []) if t and str(t).strip()]

    if not com_id:
        return JsonResponse({"ok": False, "msg": "com_id가 없습니다."}, status=400)

    # 본인 소유 문서만
    try:
        doc = Complaints.objects.get(com_id=int(com_id), username=request.user.username)
    except (DoesNotExist, ValidationError, ValueError):
        return JsonResponse({"ok": False, "msg": "민원을 찾을 수 없습니다."}, status=404)

    # 업데이트 필드 구성(빈 값은 무시)
    updates = {}
    if content:
        updates["com_contents"] = content
    if raw_type is not None:
        if isinstance(doc.com_type, list):
            updates["com_type"] = type_list  # 문서가 리스트면 리스트
        else:
            updates["com_type"] = ", ".join(type_list)  # 문서가 문자열이면 문자열
    if location:
        updates["com_location"] = location

    if not updates:
        return JsonResponse({"ok": False, "msg": "변경할 값이 없습니다."}, status=400)

    try:
        for k, v in updates.items():
            setattr(doc, k, v)
        doc.save()
    except ValidationError as e:  # ← 500 대신 400으로 명확한 에러
        return JsonResponse({"ok": False, "msg": f"저장 실패: {e}"}, status=400)

    return JsonResponse({"ok": True})



def custom_login_view(request):
    # 로그인 처리 코드...
    # 로그인 성공 시
    next_url = request.GET.get('next') or 'default_home'
    return redirect(next_url)


