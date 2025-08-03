from django.shortcuts import render, redirect
from django.utils import timezone
from common.models_mongo import Complaints, ComplaintStatus
from datetime import datetime

# 안전한 com_id 생성 함수
#def get_next_com_id():
    #return Counter.objects(name="complaint").modify(upsert=True, new=True, inc__seq=1).seq

def complain_add(request):
    if not request.user.is_authenticated:
        return render(request, 'complain/complain_add.html', {
            'today_date': datetime.today().strftime('%Y-%m-%d'),
            'all_complaints': [],
            'show_login_required_modal': True  # 모달 표시용 플래그
        })

    if request.method == 'POST':
        username = request.user.username if request.user.is_authenticated else 'anonymous'
        com_types = request.POST.getlist('com_type')
        com_type = ', '.join(com_types)  # 예: "청소요청, 불법투기"
        com_contents = request.POST.get('com_contents')
        com_location = request.POST.get('com_location')
        com_reg_date = timezone.now()

        #latitude = request.POST.get('latitude')
        #longitude = request.POST.get('longitude')

        com_pic1 = request.FILES.get('com_pic1')
        com_pic2 = request.FILES.get('com_pic2')
        pic1_data = com_pic1.read() if com_pic1 else None
        pic2_data = com_pic2.read() if com_pic2 else None

        # com_id를 안전하게 생성
        #next_com_id = get_next_com_id()
        last_complaint = Complaints.objects.order_by('-com_id').first()
        next_com_id = last_complaint.com_id + 1 if last_complaint else 1

        # 1. complaints 저장
        complaint = Complaints(
            com_id=next_com_id,
            username=username,
            com_type=com_type,
            com_title=f"{com_type} 신고",
            com_contents=com_contents,
            com_location=com_location,
            com_reg_date=com_reg_date,
            com_pic1=pic1_data,
            com_pic2=pic2_data,
            t_district_id=0,
            re_complain="",
            status_id=None,
            com_trashcan="",
            com_trash_type="",
        )

        #if latitude:
            #complaint.latitude = float(latitude)
        #if longitude:
            #complaint.longitude = float(longitude)

        complaint.save()

        # 2. complaint_status 저장 (com_id 연동)
        status = ComplaintStatus(
            com_id=next_com_id,
            status_name="처리중",
            updated_at=timezone.now()
        )
        status.save()

        return render(request, 'complain/complain_add.html', {
            'today_date': datetime.today().strftime('%Y-%m-%d'),
            'all_complaints': Complaints.objects.order_by('-com_reg_date')[:10],
            'show_success_modal': True
        })

    # 사용자 민원 전체 리스트를 가져와 템플릿으로 전달
    username = request.user.username if request.user.is_authenticated else 'anonymous'
    user_complaints = Complaints.objects(username=username).order_by('-com_reg_date')[:10]

    all_complaints_json = [
        {
            'com_location': c.com_location,
            'com_type': c.com_type,
            'com_contents': c.com_contents,
            'com_reg_date': c.com_reg_date.strftime('%Y-%m-%d')
        }
        for c in user_complaints
    ]

    return render(request, 'complain/complain_add.html', {
        'today_date': datetime.today().strftime('%Y-%m-%d'),
        'all_complaints': all_complaints_json,
    })

