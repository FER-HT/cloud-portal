import re,os,time
from django.http import Http404
from django.http import HttpResponse
from django.template import Template, Context, loader
from django.shortcuts import render
from django.db import transaction
from portal.models import *

import paramiko

def index(request):

    out, err = remote_exec("uptime")
    data = { "out" : out }

    data["machines"] = get_remote_running_machines()

    data["packages"] = Package.objects.order_by("name")
    data["deployed_packages"] = DeployedPackage.objects.order_by("ctime")


    return render(request, 'index.html', data)

def launch(request):
    package = Package.objects.get(pk = int(request.POST['package_id']))
    services = package.service_set.order_by("order")

    data = {"package" : package, "services" : services}

    dp = DeployedPackage(package = package)
    dp.save()
    dservices = []
    uniq = int(time.time()) % 10000
    count = 1
    for s in services:
        hostname = "%s-%d-%d" % (s.ident, uniq, count)
        count += 1
        tpl = Template(s.cloud_init_template)
        ctx = Context({
            "name" : s.name,
            "ident" : s.ident,
            "state" : DeployedPackageService.STATE_NEW,
            "package" : package,
            "deployed_package" : dp
        })
        cloud_init = tpl.render(ctx)
        dps = dp.deployedpackageservice_set.create(service=s, cloud_init=cloud_init, hostname=hostname)
        dps.save()

    data["deployed_package"] = dp

    return render(request, 'launch.html', data)

def checkrun(request):
    dp = DeployedPackage.objects.get(pk = int(request.POST['dp_id']))
    data = { "dp" : dp }
    result = []
    machines = get_remote_running_machines()
    for dps in dp.deployedpackageservice_set.order_by("service__order"):
        result.append((dps, do_checkrun(dps, machines)))
    data["result"] = result
    return render(request, "checkrun.html", data)


# Checks if the machine on the host is running, starts it if not
def do_checkrun(dps, machines = None):
    if not machines:
        machines = get_remote_running_machines()
    msg = None
    if dps.guid:
        # The machine has been seen already, check if it's Ok
        found_machine = None
        for m in machines:
            if m["guid"] == dps.guid:
                found_machine = m
                break
        if found_machine:
            # The machine is registered in the database and present on the host
            if found_machine["status"] != "ACTIVE":
                # The machine is in an invalid state, restart it
                do_remote_machine_delete(dps)
                dps.guid = do_remote_machine_start(dps)
                msg = "Restarted; new GUID: %s" % dps.guid
            else:
                dps.state = DeployedPackageService.STATE_RUNNING
                msg = "Active"
        else:
            # The machine is registered in the database but not present on the host
            dps.guid = do_remote_machine_start(dps)
            msg = "Missing; new GUID: %s" % dps.guid
    else:
        # Apparently, the machine was never started before. Start it now.
        dps.guid = do_remote_machine_start(dps)
        dps.sate = DeployedPackageService.STATE_RUNNING
        msg = "Started; new GUID: %s" % dps.guid
    dps.save()
    return msg


# Deleta a machine
def do_remote_machine_delete(dps):
    remote_exec_nova("delete %s" % dps.guid)


# Start a machine.
re_nova_boot = re.compile(r"([a-zA-Z].+?)\s+[|]\s+(.+?)\s+[|]")

def do_remote_machine_start(dps):
    # 1) Create a cloud-init file
    cifn = os.tempnam("/tmp", "cinit")
    cmd = "cat <<EOF>%s\n%s\nEOF\n" % (cifn, dps.cloud_init)
    remote_exec(cmd)
    # 2) Issue the "nova boot" command
    cmd = "boot --flavor %s --image %s --user_data %s --key_name portal %s" % (dps.service.nova_flavor, dps.service.nova_image, cifn, dps.hostname)
    out, err = remote_exec_nova(cmd)
    print cmd
    print out
    print err
    # 3) Parse the result
    props = {}
    for prop in re_nova_boot.findall(out):
        props[prop[0]] = prop[1]
    print props
    dps.props = repr(props)
    dps.guid = props['id']
    dps.save()
    # 4) Delete the cloud-init file
    remote_exec("rm %s" % cifn)
    return dps.guid


# Get a usefully structured list of running machines
re_nova_list = re.compile(r"([0-9a-f].......-....-....-....-............)\s+[|]\s+(.+?)\s+[|]\s+(.+?)\s+[|]\s+(.+?)\s+[|]")

def get_remote_running_machines():
    out, err = remote_exec_nova("list")
    machines_raw = re_nova_list.findall(out)
    machines = [ { "guid" : x[0], "name" : x[1], "status" : x[2], "networks" : parse_networks(x[3]) } for x in machines_raw ]
    return machines

re_networks = re.compile(r"(\w+)=(.+?)(;|$)")

def parse_networks(s):
    networks = [ { x[0] : [y.strip() for y in x[1].split(",")] } for x in re_networks.findall(s) ]
    return networks


# Execute a remote command, return the contents of stdout, stderr streams
def remote_exec(cmd, indata=None):
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.WarningPolicy())
    client.connect("chefnode4", 22, "puser", "puser22")

    stdin, stdout, stderr = client.exec_command(cmd)
    if indata:
        stdin.write(indata)
        stdin.flush()
    out = stdout.read()
    err = stderr.read()
    client.close()
    return (out, err)


# Execute "nova" with authentication
def remote_exec_nova(params):
    env = """export OS_AUTH_URL=http://161.53.67.218:5000/v2.0 && export OS_TENANT_ID=f4fca0d5bad54125932a01e3f521f6ca && export OS_TENANT_NAME="admin" && export OS_USERNAME=portal && export OS_PASSWORD=portaladm"""
    cmd = "%s && nova %s" % (env, params)
    return remote_exec(cmd)

