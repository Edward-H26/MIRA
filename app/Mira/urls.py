from django.urls import path
from . import views

app_name = "Mira"
urlpatterns = [
    path('', views.home, name='home'),
]