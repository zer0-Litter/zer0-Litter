
from django.shortcuts import render

# Create your views here.
def complain_add(request):
    return render(request, 'complain/complain_add.html')