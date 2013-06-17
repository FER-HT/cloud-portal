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
    order = models.PositiveIntegerField(default = 0)
    min_instances = models.PositiveIntegerField(default = 1)
    max_instances = models.PositiveIntegerField(default = 1)

    def __unicode__(self):
        return self.name

class Deployment(models.Model):
    name = models.CharField(max_length=200)

    def __unicode__(self):
        return self.name

class DeployedPackage(models.Model):
    deployment = models.ForeignKey(Deployment)
    package = models.ForeignKey(Package)

    def __unicode__(self):
        return "%s on %s" % (self.package.name, self.deployment.name)

class DeployedPackageService(models.Model):
    STATE_NEW = 0
    STATE_RUNNING = 1
    STATE_CRASHED = 2
    STATE_DISABLED = 3
    STATE_CHOICES = (
        (STATE_NEW,      "New"),
        (STATE_RUNNING,  "Running"),
        (STATE_CRASHED,  "Crashed / unknown"),
        (STATE_DISABLED, "Disabled")
    )

    deployed_package = models.ForeignKey(DeployedPackage)
    service = models.ForeignKey(Service)
    cloud_init = models.TextField()
    address = models.CharField(max_length=100)
    state = models.PositiveIntegerField(choices = STATE_CHOICES, default = STATE_CHOICES)

    def __unicode__(self):
        return "%s on %s on %s" % (self.service.name, self.deployment_package.package.name, self.deployment_package.deployment.name)
