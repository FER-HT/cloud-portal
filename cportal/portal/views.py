# Create your views here.
from django.http import Http404
from django.http import HttpResponse
from django.template import Template, Context, loader
from django.shortcuts import render
from django.db import transaction
from portal.models import *

import paramiko

def index(request):
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.WarningPolicy())
    client.connect("chefnode4", 22, "puser", "puser22")

    stdin, stdout, stderr = client.exec_command("uptime")
    out = stdout.read()
    client.close()

    data = { "out" : out }

    data["packages"] = Package.objects.order_by("name")


    return render(request, 'index.html', data)

def launch(request):
    package = Package.objects.get(pk = int(request.POST['package_id']))
    services = package.service_set.order_by("order")

    data = {"package" : package, "services" : services}

    dp = DeployedPackage(package = package)
    dp.save()
    dservices = []
    for s in services:
        tpl = Template(s.cloud_init_template)
        ctx = Context({
            "name" : s.name,
            "ident" : s.ident,
            "state" : DeployedPackageService.STATE_NEW,
            "package" : package,
            "deployed_package" : dp
        })
        cloud_init = tpl.render(ctx)
        dps = dp.deployedpackageservice_set.create(service=s, cloud_init=cloud_init)
        dps.save()

    data["deployed_package"] = dp

    return render(request, 'launch.html', data)


