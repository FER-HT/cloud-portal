# Create your views here.
from django.http import Http404
from django.http import HttpResponse
from django.template import Context, loader
from django.shortcuts import render

import paramiko

def index(request):
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.WarningPolicy())
    client.connect("chefnode4", 22, "puser", "puser22")

    stdin, stdout, stderr = client.exec_command("ls -la /")
    out = stdout.read()
    client.close()

    data = { "out" : out }
    return render(request, 'portal/index.html', data)

