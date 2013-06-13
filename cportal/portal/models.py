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
    cloud_init_template = models.TextField()

    def __unicode__(self):
        return self.name

class Deployment(models.Model):
    name = models.CharField(max_length=200)

    def __unicode__(self):
        return self.name

class DeploymentPackage(models.Model):
    deployment = models.ForeignKey(Deployment)
    package = models.ForeignKey(Package)

    def __unicode__(self):
        return "%s on %s" % (self.package.name, self.deployment.name)

class DeploymentPackageService(models.Model):
    deployment_package = models.ForeignKey(DeploymentPackage)
    service = models.ForeignKey(Service)
    cloud_init = models.TextField()
    address = models.CharField(max_length=100)

    def __unicode__(self):
        return "%s on %s on %s" % (self.service.name, self.deployment_package.package.name, self.deployment_package.deployment.name)
