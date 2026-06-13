from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from common.models_mongo import Complaints, ComplaintStatus, Counter, ReComplaints
from common.utils import normalize_com_types
from django.http import Http404, JsonResponse
from uuid import uuid4
from mongoengine.queryset.visitor import Q
from datetime import datetime, timedelta
from django.core.paginator import Paginator
from django.utils.http import url_has_allowed_host_and_scheme
import os
import logging

logger = logging.getLogger(__name__)


def _safe_next(request, candidate, fallback):
    """오픈 리다이렉트 방지: 내부 경로만 허용하고, 아니면 fallback 사용."""
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return fallback


def _page_range(page_obj, window=2):
    """현재 페이지 기준 최대 (2*window+1)개의 페이지 번호 범위를 만든다.
    스태프 목록 3곳에 중복돼 있던 로직을 한 곳으로 모은 것."""
    current = page_obj.number
    total = page_obj.paginator.num_pages
    if total <= (2 * window + 1):
        return range(1, total + 1)
    start = max(1, current - window)
    end = min(total, current + window)
    while end - start < (2 * window):
        if start > 1:
            start -= 1
        elif end < total:
            end += 1
        else:
            break
    return range(start, end + 1)

def init_or_fix_all_counters():
    # --- complaints의 com_id 카운터 초기화 ---
    last_complaint = Complaints.objects.order_by('-com_id').first()
    max_com_id = last_complaint.com_id if last_complaint and last_complaint.com_id else 0
    c1 = Counter.objects(name="complaint").first()
    if not c1 or (c1.seq or 0) < max_com_id:
        Counter.objects(name="complaint").update_one(upsert=True, set__seq=max_com_id)
        logger.info("complaint Counter 초기화: seq=%s", max_com_id)

    # --- complaint_status의 status_id 카운터 초기화 ---
    last_status = ComplaintStatus.objects.order_by('-status_id').first()
    max_status_id = last_status.status_id if last_status and last_status.status_id else 0
    c2 = Counter.objects(name="complaint_status").first()
    if not c2 or (c2.seq or 0) < max_status_id:
        Counter.objects(name="complaint_status").update_one(upsert=True, set__seq=max_status_id)
        logger.info("complaint_status Counter 초기화: seq=%s", max_status_id)

    logger.info("모든 Counter 초기화 완료")

#안전한 com_id 생성 함수
def get_next_com_id():
    # 필요 시 한 번만 init_or_fix_counter()를 호출해 두세요.
    return Counter.objects(name="complaint").modify(upsert=True, new=True, inc__seq=1).seq

def get_next_status_id():
    return Counter.objects(name="complaint_status").modify(upsert=True, new=True, inc__seq=1).seq



@login_required(login_url='accounts:login')
def complain_add(request):
    username = request.user.username

    if request.method == "GET":
        lat = request.GET.get("lat")
        lon = request.GET.get("lon")
        address = request.GET.get("address")

        qs = Complaints.objects(user_id=request.user.id).order_by('-com_reg_date')[:10]
        all_complaints = []
        for c in qs:
            # 타입 문자열 통일: 공백 제거 + 빈 값 제거
            type_display = ', '.join(normalize_com_types(c.com_type))
            all_complaints.append({
                "com_id": c.com_id,
                "com_type": type_display,
                "com_location": c.com_location or "",
                "com_contents": c.com_contents or "",
                "com_reg_date": c.com_reg_date.strftime('%Y-%m-%d') if c.com_reg_date else "",
            })

        return render(request, 'complain/complain_add.html', {
            'kakao_api_key': os.getenv('KAKAO_MAP_API_KEY'),
            'district_id': '11000',
            'address': address,
            'lat': lat,
            'lon': lon,
            'initial': {'lat': lat, 'lon': lon, 'address': address},
            'today_date': timezone.now().strftime('%Y-%m-%d'),
            'all_complaints': all_complaints,
            'is_reuse': request.GET.get('is_reuse', 'N'),
            'origin_com_id': request.GET.get('origin_com_id',''),
        })

    # POST 요청: 민원 저장
    com_types = [t.strip() for t in request.POST.getlist('com_type') if t.strip()]
    com_type = ', '.join(com_types)
    com_contents = (request.POST.get('com_contents') or '').strip()
    com_location = (request.POST.get('com_location') or '').strip()

    # 필수값 검증 (미입력 시 500 대신 안내 후 복귀)
    if not com_types:
        messages.error(request, '민원 유형을 1개 이상 선택해 주세요.')
        return redirect('complain:complain_add')
    if not com_contents:
        messages.error(request, '민원 내용을 입력해 주세요.')
        return redirect('complain:complain_add')
    if len(com_contents) > 5000:
        messages.error(request, '민원 내용은 5000자를 초과할 수 없습니다.')
        return redirect('complain:complain_add')

    # (옵션) 지역 기본 prefix
    if com_location and not com_location.startswith("서울특별시"):
        com_location = "서울특별시 " + com_location

    # 재민원 플래그/원본 com_id
    is_reuse = (request.POST.get('is_reuse') == 'Y')
    origin_raw = (request.POST.get('origin_com_id') or '').strip()
    origin_com_id = int(origin_raw) if origin_raw.isdigit() else None

    if is_reuse and origin_com_id:
        owned = Complaints.objects(user_id=request.user.id, com_id=origin_com_id).first()
        if not owned:
            messages.error(request, '잘못된 재민원 요청입니다.')
            return redirect('accounts:mypage_home')

    # 파일
    com_pic1 = request.FILES.get('com_pic1')
    com_pic2 = request.FILES.get('com_pic2')
    pic1_data = com_pic1.read() if com_pic1 else None
    pic2_data = com_pic2.read() if com_pic2 else None

    # 위치 (잘못된 값이 와도 500이 나지 않도록 방어)
    def _to_float(v):
        try:
            return float(v) if v else None
        except (TypeError, ValueError):
            return None

    lat = _to_float(request.POST.get('lat'))
    lon = _to_float(request.POST.get('lon'))

    # 새 com_id
    new_com_id = get_next_com_id()   # ← 변수명 통일

    try:
        # 1) Complaints 저장
        complaint = Complaints(
            com_id=new_com_id,
            user_id=request.user.id,
            username=username,
            com_type=com_type,
            com_contents=com_contents,
            com_location=com_location,
            com_reg_date=timezone.now(),
            com_pic1=pic1_data,
            com_pic2=pic2_data,
            t_district_id=0,
            com_trashcan="",
            com_trash_type="",
            re_complain='Y' if is_reuse else 'N',   # ← 중복 제거 (한 번만)
            lat=lat,
            lon=lon,
            current_status='처리중',
        )
        complaint.save()

        # 2) ComplaintStatus 저장 (초기 상태: 처리중)
        new_status_id = get_next_status_id()
        status_doc = ComplaintStatus(
            status_id=new_status_id,
            com_id=new_com_id,           # ← 변수명 수정
            status_name='처리중',
            updated_at=timezone.now()
        )
        status_doc.save()

        # 3) ReComplaints 저장 (재민원일 때만)
        if is_reuse and origin_com_id:
            ReComplaints(
                re_request_id=str(uuid4()),         # ← uuid4 import됨
                username=username,
                origin_com_id=origin_com_id,
                new_com_id=new_com_id,
                status_id=status_doc,               # ReferenceField
                re_complain='Y',
                created_at=timezone.now()
            ).save()
    except Exception as e:
        logger.error("민원 저장 실패: %s", e, exc_info=True)
        messages.error(request, '민원 등록 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.')
        return redirect('complain:complain_add')

    messages.success(request, '민원이 정상적으로 등록되었습니다.')
    return redirect('accounts:mypage_home')


@login_required(login_url='accounts:login')
def complain_reuse(request, com_id):
    # IDOR 방지: 본인이 작성한 민원만 재사용 가능 (소유권은 user_id 기준)
    obj = Complaints.objects(com_id=int(com_id), user_id=request.user.id).first()
    if not obj:
        raise Http404("해당 민원을 찾을 수 없습니다.")

    types = normalize_com_types(obj.com_type)
    lat = getattr(obj, 'lat', None) or getattr(obj, 'com_lat', None) or ''
    lon = getattr(obj, 'lon', None) or getattr(obj, 'com_lon', None) or ''
    reuse_data = {
        'location': obj.com_location or '',
        'address': obj.com_location or '',
        'types': types,
        'contents': obj.com_contents or '',
        'date': timezone.now().strftime('%Y-%m-%d'),
        'lat': lat,
        'lon': lon,
    }

    # 최근 민원 10건(그대로 유지)
    qs = Complaints.objects(user_id=request.user.id).order_by('-com_reg_date')[:10]
    all_complaints = []
    for c in qs:
        type_display = ', '.join(normalize_com_types(c.com_type))
        all_complaints.append({
            "com_id": c.com_id,
            "com_type": type_display,
            "com_location": c.com_location or "",
            "com_contents": c.com_contents or "",
            "com_reg_date": c.com_reg_date.strftime('%Y-%m-%d') if c.com_reg_date else "",
        })

    return render(request, 'complain/complain_add.html', {
        'initial': reuse_data,
        'lat': lat,
        'lon': lon,
        'today_date': reuse_data['date'],
        'is_reuse': 'Y',
        'origin_com_id': obj.com_id,
        'all_complaints': all_complaints,
        'kakao_api_key': os.getenv('KAKAO_MAP_API_KEY'),
        'district_id': '11000',
    })

@login_required
@require_GET
def old_complaints_api(request):
    limit = int(request.GET.get('limit', 10))

    qs = Complaints.objects(user_id=request.user.id).order_by('-com_reg_date')[:limit]
    items = []
    for c in qs:
        type_display = ', '.join(normalize_com_types(c.com_type))

        items.append({
            "com_id": c.com_id,
            "type": type_display,
            "date": c.com_reg_date.strftime('%Y-%m-%d') if c.com_reg_date else "",
            "location": c.com_location or "",
            "contents": c.com_contents or "",
        })

    return JsonResponse({"items": items})

@staff_member_required
@require_GET
def all_complaints_staff(request):
    page_obj, query = build_staff_items(request, force_status=None)
    page_range = _page_range(page_obj)

    return render(request, "complain/staff_all_list.html", {
        "page_obj": page_obj,
        "query": query,
        "page_range": page_range,  # ← 추가
    })


@staff_member_required
@require_GET
def pending_list(request):
    page_obj, query = build_staff_items(request, force_status="처리중")
    page_range = _page_range(page_obj)

    return render(request, "complain/staff_pending_list.html", {
        "page_obj": page_obj,
        "query": query,
        "page_range": page_range,
    })

@staff_member_required
@require_GET
def completed_list(request):
    page_obj, query = build_staff_items(request, force_status="처리완료")
    page_range = _page_range(page_obj)

    return render(request, "complain/staff_completed_list.html", {
        "page_obj": page_obj,
        "query": query,
        "page_range": page_range,
    })


@staff_member_required
@require_POST
def mark_complaint_completed(request, com_id: int):
    """처리중 → 처리완료 (이력 1줄 추가 + 감사추적). 필요시 캐시도 갱신"""
    # 오픈 리다이렉트 방지: 외부 URL은 무시하고 내부 경로만 허용
    next_url = _safe_next(request, request.POST.get("next"), "complain:pending_list")

    comp = Complaints.objects(com_id=int(com_id)).first()
    if not comp:
        return redirect(next_url)

    # 이미 최신이 완료면 중복 방지
    last = ComplaintStatus.objects(com_id=comp.com_id).order_by("-updated_at", "-status_id").first()
    if last and last.status_name == "처리완료":
        return redirect(next_url)

    # 1) 이력 추가 (감사추적: changed_by, status_note, 시각)
    ComplaintStatus(
        status_id=get_next_status_id(),
        com_id=comp.com_id,
        status_name="처리완료",
        changed_by=request.user.username,
        updated_at=timezone.now(),
    ).save()

    # 2) 최신 상태 비정규화 필드 갱신(목록/통계 성능용)
    comp.update(set__current_status="처리완료")

    return redirect(next_url)

# --- 공통 파서 ---
def _parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None

def _parse_int(s):
    try:
        return int(s)
    except Exception:
        return None

# --- 관리자 공통 아이템 빌드 (검색/필터/기간/페이지네이션) ---
def build_staff_items(request, force_status=None):
    """
    force_status: '처리중' or '처리완료' or None
    """
    q = (request.GET.get('q') or '').strip()
    status = (request.GET.get('status') or '').strip()
    d_from = (request.GET.get('from') or '').strip()
    d_to = (request.GET.get('to') or '').strip()

    base_q = Q()
    # 검색: 내용/주소/유형/작성자/번호(#17같은 형태 포함)
    if q:
        maybe_id = _parse_int(q.lstrip('#'))
        text_q = (
            Q(com_contents__icontains=q) |
            Q(com_location__icontains=q) |
            Q(com_type__icontains=q) |
            Q(username__icontains=q)
        )
        if maybe_id is not None:
            text_q |= Q(com_id=maybe_id)
        base_q &= text_q

    gte, lte = _parse_date(d_from), _parse_date(d_to)
    if gte and lte and gte > lte:
        gte, lte = lte, gte
    if gte:
        base_q &= Q(com_reg_date__gte=gte)
    if lte:
        base_q &= Q(com_reg_date__lt=lte + timedelta(days=1))  # 종료일 포함

    # 상태 필터를 DB 레벨에서 적용(비정규화된 current_status 사용 → 전수 로딩/항목별 상태조회 제거)
    want = force_status or (status if status in ('처리중', '처리완료') else None)
    if want:
        base_q &= Q(current_status=want)

    docs = (Complaints.objects(base_q)
            .only('com_id', 'username', 'com_type', 'com_location',
                  'com_reg_date', 'com_contents', 'current_status')
            .order_by('-com_reg_date'))

    # 페이지네이션을 쿼리셋에 직접 적용 → 현재 페이지(5건)만 로드
    paginator = Paginator(docs, 5)
    page_obj = paginator.get_page(request.GET.get('page'))

    # 현재 페이지 항목(최대 5건)에 대해서만 담당자/완료시각 표시용 최신 이력 조회
    items = []
    for c in page_obj.object_list:
        last = (ComplaintStatus.objects(com_id=c.com_id)
                .only('status_name', 'changed_by', 'updated_at', 'status_id')
                .order_by('-updated_at', '-status_id')
                .first())
        items.append({'doc': c, 'last': last, 'latest_status': c.current_status or '처리중'})
    page_obj.object_list = items

    return page_obj, {'q': q, 'status': status, 'from': d_from, 'to': d_to}
