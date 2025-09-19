from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from common.models_mongo import Complaints, ComplaintStatus, Counter, ReComplaints
from common.models import TrashLoc
from django.http import Http404, JsonResponse
from uuid import uuid4
from mongoengine.queryset.visitor import Q
from datetime import datetime, timedelta
from django.core.paginator import Paginator
import os

def init_or_fix_all_counters():
    # --- complaints의 com_id 카운터 초기화 ---
    last_complaint = Complaints.objects.order_by('-com_id').first()
    max_com_id = last_complaint.com_id if last_complaint and last_complaint.com_id else 0
    c1 = Counter.objects(name="complaint").first()
    if not c1 or (c1.seq or 0) < max_com_id:
        Counter.objects(name="complaint").update_one(upsert=True, set__seq=max_com_id)
        print(f"complaint Counter 초기화: seq={max_com_id}")

    # --- complaint_status의 status_id 카운터 초기화 ---
    last_status = ComplaintStatus.objects.order_by('-status_id').first()
    max_status_id = last_status.status_id if last_status and last_status.status_id else 0
    c2 = Counter.objects(name="complaint_status").first()
    if not c2 or (c2.seq or 0) < max_status_id:
        Counter.objects(name="complaint_status").update_one(upsert=True, set__seq=max_status_id)
        print(f"complaint_status Counter 초기화: seq={max_status_id}")

    print("모든 Counter 초기화 완료!")

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

        qs = Complaints.objects(username=username).order_by('-com_reg_date')[:10]
        all_complaints = []
        for c in qs:
            type_display = ', '.join([t.strip() for t in c.com_type]) if isinstance(c.com_type, list) else ', '.join([s.strip() for s in c.com_type.split(',')])
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
        })

    # POST 요청: 민원 저장
    com_types = [t.strip() for t in request.POST.getlist('com_type') if t.strip()]
    com_type = ', '.join(com_types)
    com_contents = (request.POST.get('com_contents') or '').strip()
    com_location = (request.POST.get('com_location') or '').strip()

    # (옵션) 지역 기본 prefix
    if com_location and not com_location.startswith("서울특별시"):
        com_location = "서울특별시 " + com_location

    # 재민원 플래그/원본 com_id
    is_reuse = (request.POST.get('is_reuse') == 'Y')
    origin_raw = (request.POST.get('origin_com_id') or '').strip()
    origin_com_id = int(origin_raw) if origin_raw.isdigit() else None

    if is_reuse and origin_com_id:
        owned = Complaints.objects(username=username, com_id=origin_com_id).first()
        if not owned:
            from django.contrib import messages
            messages.error(request, '잘못된 재민원 요청입니다.')
            return redirect('accounts:mypage_home')

    # 파일
    com_pic1 = request.FILES.get('com_pic1')
    com_pic2 = request.FILES.get('com_pic2')
    pic1_data = com_pic1.read() if com_pic1 else None
    pic2_data = com_pic2.read() if com_pic2 else None

    # 위치
    lat_raw = request.POST.get('lat')
    lon_raw = request.POST.get('lon')
    lat = float(lat_raw) if lat_raw else None
    lon = float(lon_raw) if lon_raw else None

    # 위도경도저장확인용
    print(f"[DEBUG] lat={lat}, lon={lon}")

    # 새 com_id
    new_com_id = get_next_com_id()   # ← 변수명 통일

    # 1) Complaints 저장
    complaint = Complaints(
        com_id=new_com_id,
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

    from django.contrib import messages
    messages.success(request, '민원이 정상적으로 등록되었습니다.')
    return redirect('accounts:mypage_home')


def trash_bin_map(request, district_id=None):
    if district_id:
        trashcans = TrashLoc.objects.filter(t_district_id=district_id)
    else:
        trashcans = TrashLoc.objects.all()

    data = [
        {
            "t_lat": float(t.t_lat),
            "t_lon": float(t.t_lon),
            "t_road_addr": t.t_addr,
            "t_detailed_addr": t.t_detailed_addr,
            "t_trash_type": t.t_trash_type,
            "t_loc": t.t_loc,
            "t_dept": t.t_dept,
            "t_contact": t.t_contact,
            "t_district_id": t.t_district_id,
        }
        for t in trashcans
    ]
    return JsonResponse(data, safe=False)


@login_required(login_url='accounts:login')
def complain_reuse(request, com_id):
    obj = Complaints.objects(com_id=int(com_id)).first()
    if not obj:
        raise Http404("해당 민원을 찾을 수 없습니다.")

    types = obj.com_type if isinstance(obj.com_type, list) \
        else [s.strip() for s in str(obj.com_type).split(',') if s.strip()]

    reuse_data = {
        'location': obj.com_location,
        'types': types,
        'contents': obj.com_contents or '',
        'date': timezone.now().strftime('%Y-%m-%d')
    }

    qs = Complaints.objects(username=request.user.username).order_by('-com_reg_date')[:10]
    all_complaints = []
    for c in qs:
        if isinstance(c.com_type, list):
            type_display = ', '.join([t.strip() for t in c.com_type if str(t).strip()])
        else:
            type_display = ', '.join([s.strip() for s in str(c.com_type).split(',') if s.strip()])
        all_complaints.append({
            "com_id": c.com_id,
            "com_type": type_display,
            "com_location": c.com_location or "",
            "com_contents": c.com_contents or "",
            "com_reg_date": c.com_reg_date.strftime('%Y-%m-%d') if c.com_reg_date else "",
        })

    return render(request, 'complain/complain_add.html', {
        'initial': reuse_data,
        'today_date': reuse_data['date'],
        'is_reuse': 'Y',
        'origin_com_id': obj.com_id,
        'all_complaints': all_complaints,
    })

@login_required
@require_GET
def old_complaints_api(request):
    username = request.user.username
    limit = int(request.GET.get('limit', 10))

    qs = Complaints.objects(username=username).order_by('-com_reg_date')[:limit]
    items = []
    for c in qs:
        # 타입 문자열 정리
        if isinstance(c.com_type, list):
            type_display = ', '.join([t.strip() for t in c.com_type if str(t).strip()])
        else:
            type_display = ', '.join([s.strip() for s in str(c.com_type).split(',') if s.strip()])

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
    return render(request, "complain/staff_all_list.html", {
        "page_obj": page_obj,
        "query": query,
    })

@staff_member_required
@require_GET
def pending_list(request):
    page_obj, query = build_staff_items(request, force_status="처리중")
    return render(request, "complain/staff_pending_list.html", {
        "page_obj": page_obj,
        "query": query,
    })

@staff_member_required
@require_GET
def completed_list(request):
    page_obj, query = build_staff_items(request, force_status="처리완료")
    return render(request, "complain/staff_completed_list.html", {
        "page_obj": page_obj,
        "query": query,
    })

@staff_member_required
@require_POST
def mark_complaint_completed(request, com_id: int):
    """처리중 → 처리완료 (이력 1줄 추가 + 감사추적). 필요시 캐시도 갱신"""
    next_url   = request.POST.get("next")

    comp = Complaints.objects(com_id=int(com_id)).first()
    if not comp:
        return redirect(next_url or "complain:pending_list")

    # 이미 최신이 완료면 중복 방지
    last = ComplaintStatus.objects(com_id=comp.com_id).order_by("-updated_at", "-status_id").first()
    if last and last.status_name == "처리완료":
        return redirect(next_url or "complain:pending_list")

    # 1) 이력 추가 (감사추적: changed_by, status_note, 시각)
    ComplaintStatus(
        status_id=get_next_status_id(),
        com_id=comp.com_id,
        status_name="처리완료",
        changed_by=request.user.username,
        updated_at=timezone.now(),
    ).save()


    return redirect(next_url or "complain:pending_list")

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

    docs = (Complaints.objects(base_q)
            .only('com_id','username','com_type','com_location','com_reg_date','com_contents')
            .order_by('-com_reg_date'))

    items = []
    for c in docs:
        last = (ComplaintStatus.objects(com_id=c.com_id)
                .only('status_name','changed_by','updated_at','status_id')
                .order_by('-updated_at', '-status_id')
                .first())
        latest_status = last.status_name if last else '처리중'

        items.append({'doc': c, 'last': last, 'latest_status': latest_status})

    # 상태 필터(강제/선택)
    want = force_status or (status if status in ('처리중','처리완료') else None)
    if want:
        items = [it for it in items if it['latest_status'] == want]

    # 페이지네이션 (5개씩)
    paginator = Paginator(items, 5)
    page_obj = paginator.get_page(request.GET.get('page'))

    return page_obj, {'q': q, 'status': status, 'from': d_from, 'to': d_to}
