from django.urls import path, include
from . import views

app_name = "memoria"
urlpatterns = [
    path("home/", views.home, name="home"),
    path("help/", views.help_view, name="help"),
    path("privacy/", views.privacy_view, name="privacy"),
    path("", views.landing, name="landing"),
]
