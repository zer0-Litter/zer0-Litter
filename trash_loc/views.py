from django.http import HttpResponse
from django.shortcuts import render
from .models import TrashLoc
# Create your views here.

def home(request):
    return render(request, 'trash_loc/home.html')


# 테스트용! 작업할 땐 지우고 사용해주세요 (html도 포함!)
# def trash_loc_list(request):
    # trash_locs = TrashLoc.objects.all()
    #
    # return render(request, 'trash_loc_list.html', {'trash_locs': trash_locs})