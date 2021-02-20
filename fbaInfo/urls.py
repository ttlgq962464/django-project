from django.urls import path
from . import views


urlpatterns = [
    path('condition', views.parameter),
    # path('figure', views.figure),
    # path('plan', views.plan),
]