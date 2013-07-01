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

    sync_dp_with_machines(data["deployed_packages"], data["machines"])

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
        for x in range(s.max_instances):
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
            attrs = json.loads(exec_knife("node show -l -F json %s" % dps.hostname))
            flatten_dict(dps.service.ident, v, attrs[u"default"])
            flatten_dict(dps.service.ident, v, attrs[u"normal"])
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
        if type(d[k]) in (type('a'), type(u'a'), type(1), type(1.1), type(False), type(None)):
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


def checkrun(request, dp_id=None):
    if dp_id == None:
        if 'dp_id' in request.POST:
            dp = DeployedPackage.objects.get(pk = int(request.POST['dp_id']))
        elif 'dp_id' in request.GET:
            dp = DeployedPackage.objects.get(pk = int(request.GET['dp_id']))
        else:
            return HttpResponse("Unknown dp_id")
    else:
        dp = DeployedPackage.objects.get(pk = int(dp_id))

    data = { "dp" : dp }
    machines = get_remote_running_machines()
    list_running = []
    list_starting = []
    list_new = []
    for dps in dp.deployedpackageservice_set.order_by("service__order"):
        # This is a state machine, iterating towards the state where
        # there are no machines in STATE_NEW or STATE_STARTING.
        # A machine is booted with STATE_NEW.
        # A machine transitions from STATE_NEW into STATE_STARTING when it gets an IP address.
        # A machine transitions from STATE_STARTING into STATE_RUNNING when it is registered into Chef

        found = None
        for m in machines:
            if m['guid'] == dps.guid:
                found = m
                break

        if found and found['status'] == 'ERROR':
            dps.state = DeployedPackageService.STATE_CRASHED
            dps.save()
            list_new.append((dps, do_checkrun(dps, machines, False)))
            break

        if dps.state == DeployedPackageService.STATE_NEW or not found:
            list_new.append((dps, do_checkrun(dps, machines, False)))
            machines = get_remote_running_machines()
            for m in machines:
                if m['guid'] == dps.guid:
                    found = m
                    break
            if found and m['networks']:
                dps.state = DeployedPackageService.STATE_STARTING
                sync_dps_with_machine(dps, m)
            break

        if dps.state == DeployedPackageService.STATE_STARTING:
            list_starting.append(dps)
            if is_chef_machine_registered(dps.hostname):
                dps.state = DeployedPackageService.STATE_RUNNING
                dps.save()
            break

        if dps.state == DeployedPackageService.STATE_RUNNING:
            list_running.append(dps)

    data["list_running"] = list_running
    data["list_starting"] = list_starting
    data["list_new"] = list_new
    return render(request, "checkrun.html", data)


def checkrun_is_active(dps, machines = None):
    if not machines:
        machines = get_remote_running_machines()
    if dps.guid:
        found = None
        for m in machines:
            if m["guid"] == dps.guid:
                found = m
                break
        if found:
            if found["status"] == "ACTIVE":
                return True
            else:
                return False
        else:
            return None


# Checks if the machine on the host is running, starts it if not
# Does not update dps.status
def do_checkrun(dps, machines = None, wait = True):
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
            if found_machine["status"] != "ACTIVE" and found_machine["status"] != "BUILD":
                # The machine is in an invalid state, restart it
                do_remote_machine_delete(dps)
                dps.guid = do_remote_machine_start(dps)
                if dps.guid != None:
                    msg = "Restarted; new GUID: %s" % dps.guid
                    if wait:
                        wait_remote_machine_status(dps.guid, "ACTIVE")
                else:
                    msg = "Error starting!"
            else:
                msg = "Active"
        else:
            # The machine is registered in the database but not present on the host
            dps.guid = do_remote_machine_start(dps)
            if dps.guid != None:
                msg = "Missing; new GUID: %s" % dps.guid
                if wait:
                    wait_remote_machine_status(dps.guid, "ACTIVE")
            else:
                msg = "Error starting!"
    else:
        # Apparently, the machine was never started before. Start it now.
        dps.guid = do_remote_machine_start(dps)
        if dps.guid != None:
            msg = "Started; new GUID: %s" % dps.guid
            if wait:
                wait_remote_machine_status(dps.guid, "ACTIVE")
        else:
            msg = "Error starting!"

    dps.save()
    return msg


# Deleta a machine
def do_remote_machine_delete(dps):
    remote_exec_nova("delete %s" % dps.guid)
    try:
        exec_knife("node delete -y %s" % dps.hostname)
    except:
        pass


# Start a machine.
re_nova_boot = re.compile(r"([a-zA-Z].+?)\s+[|]\s+(.+?)\s+[|]")

def do_remote_machine_start(dps):
    # 1) Create a cloud-init file
    cifn = os.tempnam("/tmp", "cinit")
    init_vars = build_dp_variables(dps.deployed_package)
    init_vars["node.hostname"] = dps.hostname
    print "Starting", dps.hostname, "with", repr(init_vars)
    cloud_init = unicode(dps.cloud_init).replace("$", r"\$")
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


# Waits until the remote machine's status becomes whatever is given
# in the second argument, or until the given number of seconds have passed.
def wait_remote_machine_status(guid, status, seconds=10):
    t_start = time.time()
    while True:
        machines = get_remote_running_machines()
        found = None
        for m in machines:
            if m['guid'] == guid:
                found = m
                break
        if found:
            if m['status'] == status:
                print "OOO: %s is %s" % (m['guid'], status)
                return True
            if time.time() - t_start < seconds:
                time.sleep(0.5)
            else:
                return False
        else:
            return None


# Checks if the machine name is registered in Chef
def is_chef_machine_registered(name):
    machines = exec_knife("node list").split("\n")
    return name in machines


# Waits until the machine with the given name appears in the output
# of "knife node list".
def wait_chef_machine(name, seconds=10):
    t_start = time.time()
    while True:
        if is_chef_machine_registered(name):
            print "CCC: %s is registered" % name
            return True
        else:
            if time.time() - t_start < seconds:
                time.sleep(0.5)
            else:
                return False


# A simple template engine replacing "%{key}" substrings with values from
# a dictionary.
def simple_template(s, v):
    for k in v:
        s = s.replace("%%{%s}" % k, str(v[k]))
    return s

# Synces the network address information from the running machines list
# with the database information. The database information is used in
# build_dp_variables().
def sync_dp_with_machines(dpackages, machines):
    for dp in dpackages:
        for dps in dp.deployedpackageservice_set.all():
            for m in machines:
                if m["guid"] == dps.guid: # and (dps.address == None or dps.address == ""):
                    sync_dps_with_machine(dps, m)
                    break


def sync_dps_with_machine(dps, m):
    assert dps.guid == m["guid"]
    dps.address = json.dumps(m["networks"])
    if m["status"] == "ACTIVE":
        dps.status = DeployedPackageService.STATE_RUNNING
    elif m["status"] == "ERROR":
        dps.status = DeployedPackageService.STATE_CRASHED
    dps.save()


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
    return subprocess.check_output("knife %s" % cmd, shell=True, stderr=subprocess.STDOUT)

