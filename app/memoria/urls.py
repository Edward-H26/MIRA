from django.urls import path
from . import views

app_name = "memoria"
urlpatterns = [
    path('home/', views.home, name='home'),
    path('', views.landing, name='landing'),
]
