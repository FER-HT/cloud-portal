# Create your views here.
from django.http import Http404
from django.http import HttpResponse
from django.template import Context, loader
from django.shortcuts import render

import paramiko

def index(request):
    data = {}
    return render(request, 'portal/index.html', data)

