# dashboard/views.py
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timezone as py_tz
from common.models_mongo import Complaints


def _timeago_kor(dt):
    if not dt:
        return ""
    if timezone.is_naive(dt):
        dt = dt.replace(tzinfo=py_tz.utc)
    now = timezone.now()
    diff = now - dt
    secs = int(diff.total_seconds())
    if secs < 60:
        return "방금 전"
    mins = secs // 60
    if mins < 60:
        return f"{mins}분 전"
    hours = mins // 60
    if hours < 24:
        return f"{hours}시간 전"
    days = hours // 24
    if days < 7:
        return f"{days}일 전"
    weeks = days // 7
    return f"{weeks}주 전"


@login_required(login_url='accounts:login')
def dashboard(request):
    qs = Complaints.objects.order_by("-com_reg_date").limit(3)

    latest = []
    for c in qs:
        region = c.com_location or "서울특별시" # 챗봇은 com_location이 없으므로 서울특별시로 나오게 설정
        type_label = (c.com_type or "").strip()
        timeago = _timeago_kor(c.com_reg_date)

        latest.append({
            "region": region,
            "type_label": type_label,
            "timeago": timeago,
        })

    return render(request, "dashboard/dashboard.html", {
        "latest_complaints": latest,
    })
