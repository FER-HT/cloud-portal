import re,os,time,json,subprocess
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
    data["managed_machines"] = DeployedPackageService.objects.all().values_list("guid", flat=True)

    data["packages"] = Package.objects.order_by("name")
    data["deployed_packages"] = DeployedPackage.objects.order_by("ctime")

    sync_dps_with_machines(data["deployed_packages"], data["machines"])

    for dp in data["deployed_packages"]:
        print repr(build_dp_variables(dp))

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


def dpsop(request):
    if 'dp_id' in request.POST:
        return checkrun(request)
    elif 'rp_id' in request.POST:
        return remove(request)
    else:
        return HttpResponse("Unknown op")
       

def build_dp_variables(dp):
    """For each deployed package service, collect its local variables
    (e.g. network addresses) and Chef attributes. Return it all as a
    flat dictionary. """
    v = {}
    for dps in dp.deployedpackageservice_set.all():
        # 1st pass: build network variables
        if dps.address:
            for net in json.loads(dps.address):
                for nn in net: # net name
                    for a in net[nn]: # address
                        if ":" in a:    # XXX: do better
                            a_type = "ipv6"
                        else:
                            a_type = "ipv4"
                        v["%s.%s_%s" % (dps.service.ident, nn, a_type)] = a
        # 2nd pass: pull in all Chef's attributes from the "default"
        # and the "normal" keys of "knife node show -l"
        try:
            attrs = json.loads(exec_knife("show -l -F json %s" % node_name))
            flatten_dict(v, attrs["default"])
            flatten_dict(v, attrs["normal"])
        except:
            pass
    return v


def flatten_dict(base, v, d):
    """Take a dictionary d, iterate it and recursively flatten/add
    its values to the dictionary v. The idea is to convert a structure
    like { "k1" : "v1", "k2" : { "r1" : 0, "r2" : 1} } into
    { "k1 : "v1", "k2.r1" : 0, "k2.r2" : 1} etc."""
    if base != '':
        base = base + "."
    for k in d:
        if type(d[k]) in (type('a'), type(u'a'), 1, 1.1, False):
            v[base + k] = d[k]
        elif type(d[k]) in (type([]), type((1,2))):
            v[base + k] = ", ".join(d[k])
        elif type(d[k]) == type({}):
            flatten_dict(base + k, v, d[k])
        else:
            print "huh,", type(d[k])


def remove(request):
    dp = DeployedPackage.objects.get(pk = int(request.POST['rp_id']))
    data = { "dp" : dp }
    result = []
    machines = get_remote_running_machines()
    for dps in dp.deployedpackageservice_set.order_by("-service__order"):
        result.append((dps, do_remove(dps, machines)))
    data["result"] = result
    dp.delete()
    return render(request, "remove.html", data)


def do_remove(dps, machines = None):
    if not machines:
        machines = get_remote_running_machines()
    res = 0
    if dps.guid:
        found_machine = None
        for m in machines:
            if m["guid"] == dps.guid:
                found_machine = m
                break
        if found_machine:
            do_remote_machine_delete(dps)
            res = 1
            dps.delete()
        else:
            dps.delete()
    return res


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
                if dps.guid != None:
                    msg = "Restarted; new GUID: %s" % dps.guid
                else:
                    msg = "Error starting!"
            else:
                dps.state = DeployedPackageService.STATE_RUNNING
                msg = "Active"
        else:
            # The machine is registered in the database but not present on the host
            dps.guid = do_remote_machine_start(dps)
            if dps.guid != None:
                msg = "Missing; new GUID: %s" % dps.guid
            else:
                msg = "Error starting!"
    else:
        # Apparently, the machine was never started before. Start it now.
        dps.guid = do_remote_machine_start(dps)
        if dps.guid != None:
            dps.state = DeployedPackageService.STATE_RUNNING
            msg = "Started; new GUID: %s" % dps.guid
        else:
            msg = "Error starting!"
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
    cloud_init = unicode(dps.cloud_init).replace("$", r"\$")
    init_vars = build_dp_variables(dps.deployed_package)
    init_vars["node.hostname"] = dps.hostname
    cloud_init = simple_template(cloud_init, init_vars)
    cmd = "cat <<EOF>%s\n%s\nEOF\n" % (cifn, cloud_init)
    remote_exec(cmd)
    # 2) Issue the "nova boot" command
    cmd = "boot --flavor %s --image %s --user_data %s --key_name portal %s" % (dps.service.nova_flavor, dps.service.nova_image, cifn, dps.hostname)
    out, err = remote_exec_nova(cmd)
    print cmd
    # 3) Parse the result
    props = {}
    for prop in re_nova_boot.findall(out):
        props[prop[0]] = prop[1]
    print props
    if len(props) == 0:
        print "Error starting machine: %s / %s" % (out, err)
        return None
    dps.props = repr(props)
    dps.guid = props['id']
    dps.save()
    # 4) Delete the cloud-init file
    #remote_exec("rm %s" % cifn)
    return dps.guid


# A simple template engine replacing "%{key}" substrings with values from
# a dictionary.
def simple_template(s, v):
    for k in v:
        s = s.replace("%%{%s}" % k, v[k])
    return s

# Synces the network address information from the running machines list
# with the database information. The database information is used in
# build_dp_variables().
def sync_dps_with_machines(dpackages, machines):
    for dp in dpackages:
        for dps in dp.deployedpackageservice_set.all():
            for m in machines:
                if m["guid"] == dps.guid: # and (dps.address == None or dps.address == ""):
                    dps.address = json.dumps(m["networks"])
                    dps.save()
                    break


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
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
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

# Execute "knife"
def exec_knife(cmd, indata=None):
    ret = subprocess.check_output("knife %s" % cmd, shell=True)
    return ret

