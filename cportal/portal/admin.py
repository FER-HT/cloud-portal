from django.contrib import admin
from portal.models import *

admin.site.register(Package)
admin.site.register(Service)
admin.site.register(Deployment)
admin.site.register(DeploymentPackage)
admin.site.register(DeploymentPackageService)

