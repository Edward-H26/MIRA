from django.urls import path
from . import views

app_name = "memoria"
urlpatterns = [
    path('home/', views.home, name='home'),
    path('', views.landing, name='landing'),
    path("chat/", views.chat, name="chat"),
    path("memory/", views.memory, name="memory"),
    path("profile/", views.profile, name="profile"),
]
