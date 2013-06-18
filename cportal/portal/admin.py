from django.contrib import admin
from portal.models import *

class DeployedPackageServiceInline(admin.StackedInline):
    model = DeployedPackageService
    extra = 1

class DeployedPackageAdmin(admin.ModelAdmin):
    inlines = [DeployedPackageServiceInline]

admin.site.register(Package)
admin.site.register(Service)
admin.site.register(DeployedPackage, DeployedPackageAdmin)
admin.site.register(DeployedPackageService)


