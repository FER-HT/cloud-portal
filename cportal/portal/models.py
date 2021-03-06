from django.db import models

# Create your models here.

class Package(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField()

    def __unicode__(self):
        return self.name

class Service(models.Model):
    package = models.ForeignKey(Package)
    name = models.CharField(max_length=200)
    description = models.TextField()
    ident = models.CharField(max_length=64)
    cloud_init_template = models.TextField()
    nova_flavor = models.CharField(max_length=64)
    nova_image = models.CharField(max_length=64)
    order = models.PositiveIntegerField(default = 0)
    min_instances = models.PositiveIntegerField(default = 1)
    max_instances = models.PositiveIntegerField(default = 1)

    def __unicode__(self):
        return "%s (%s) [%d-%d]" % (self.name, self.ident, self.min_instances, self.max_instances)

class DeployedPackage(models.Model):
    package = models.ForeignKey(Package)
    ctime = models.DateTimeField(auto_now_add=True)

    def __unicode__(self):
        return "%s @ %s" % (self.package.name, self.ctime)

class DeployedPackageService(models.Model):
    STATE_NEW = 0           # IP address is still not available
    STATE_STARTING = 1      # IP address is available, but it's not registered into Chef
    STATE_RUNNING = 2       # a machine is running IFF openstack node is ACTIVE and the machine is registered into Chef
    STATE_CRASHED = 3
    STATE_DISABLED = 4
    STATE_CHOICES = (
        (STATE_NEW,      "New"),
        (STATE_STARTING, "Starting"),
        (STATE_RUNNING,  "Running"),
        (STATE_CRASHED,  "Crashed / unknown"),
        (STATE_DISABLED, "Disabled")
    )

    deployed_package = models.ForeignKey(DeployedPackage)
    service = models.ForeignKey(Service)
    cloud_init = models.TextField()
    state = models.PositiveIntegerField(choices = STATE_CHOICES, default = STATE_NEW)
    hostname = models.CharField(max_length=100)
    last_check_time = models.DateTimeField(null=True, blank=True)
    address = models.CharField(max_length=1000, null=True, blank=True)
    guid = models.CharField(max_length=64, null=True, blank=True)
    props = models.TextField(null=True, blank=True)

    def __unicode__(self):
        return "%s on %s @ %s" % (self.service.name, self.deployed_package.package.name, self.deployed_package.ctime)
