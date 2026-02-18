from django.urls import path
from . import views

app_name = "users"
urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile_view, name="profile"),
    path("avatar/<uuid:uuid>/", views.avatar_view, name="avatar"),
    path("password-change/", views.change_password_view, name="password_change"),
]
