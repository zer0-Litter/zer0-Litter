from django.http import HttpResponse
from django.shortcuts import render
from common.models import TrashLoc
# Create your views here.

def home(request):
    return render(request, 'trash_loc/home.html')

