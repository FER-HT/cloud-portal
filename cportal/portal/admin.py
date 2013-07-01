from django.contrib import admin
from portal.models import *

class DeployedPackageServiceInline(admin.StackedInline):
    model = DeployedPackageService
    extra = 1

class DeployedPackageAdmin(admin.ModelAdmin):
    inlines = [DeployedPackageServiceInline]

class PackageServiceInline(admin.StackedInline):
    model = Service
    extra = 1

class PackageAdmin(admin.ModelAdmin):
    inlines = [PackageServiceInline]

admin.site.register(Package, PackageAdmin)
admin.site.register(Service)
admin.site.register(DeployedPackage, DeployedPackageAdmin)
admin.site.register(DeployedPackageService)


