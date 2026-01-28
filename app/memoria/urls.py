from django.urls import path
from . import views

app_name = "memoria"
urlpatterns = [
    path('', views.home, name='home'),
]