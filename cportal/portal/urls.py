from django.conf.urls import patterns, url

from portal import views

urlpatterns = patterns('',
    url(r'^$', views.index, name='index'),
#    url(r'^/launch/(?P<package_id>\d+)$', views.launch, name='launch')
    url(r'^launch$', views.launch, name='launch'),     # POST URL
    url(r'^dpsop$', views.dpsop, name='dpsop'),     # POST URL
)

