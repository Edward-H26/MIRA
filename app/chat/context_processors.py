from django.apps import apps


def user_sessions(request):
    if not request.user.is_authenticated:
        return {"sessions": []}
    Profile = apps.get_model("users", "User")
    Session = apps.get_model("chat", "Session")
    profile, _ = Profile.objects.get_or_create(user=request.user)
    sessions = Session.objects.filter(user=profile).order_by("-created_at")
    return {"sessions": sessions}
