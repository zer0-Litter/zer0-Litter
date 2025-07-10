from django.http import HttpResponse
from django.shortcuts import render

# Create your views here.

def home(request):
    pass


from .models import TrashLoc

# 테스트용! 작업할 땐 지우고 사용해주세요 (html도 포함!)
def trash_loc_list(request):
    trash_locs = TrashLoc.objects.all()

    return render(request, 'trash_loc_list.html', {'trash_locs': trash_locs})