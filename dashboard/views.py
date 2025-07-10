from django.shortcuts import render

# Create your views here.
def dashboard(request):
    # 실시간 쓰레기통별 민원 현황
    return render(request, 'dashboard/dashboard.html')

def dashboard_hotspot_map(request):
    # 쓰레기통 민원지도
    return render(request, 'dashboard/dashboard.html')

def dashboard_top_reports(request):
    # 최근 민원 집중 지역
    return render(request, 'dashboard/dashboard.html')

def dashboard_report_by_time(request):
    # 시간대별 민원 현황
    return render(request, 'dashboard/dashboard.html')