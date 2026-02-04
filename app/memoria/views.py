from django.apps import apps
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template import loader

# Create your views here.
def home(request):
    template = loader.get_template("memoria/home.html")
    username = request.user.username if request.user.is_authenticated else "Guest"
    sessions = []
    memories = []
    if request.user.is_authenticated:
        Profile = apps.get_model("users", "User")
        Session = apps.get_model("chat", "Session")
        Memory = apps.get_model("chat", "Memory")
        profile, _ = Profile.objects.get_or_create(user=request.user)
        sessions = Session.objects.filter(user=profile).order_by("-created_at")
        memories = Memory.objects.filter(user=profile).order_by("-updated_at")
    context = {"username": username, "sessions": sessions, "memories": memories}
    return HttpResponse(template.render(context, request))

def landing(request):
    template = loader.get_template("memoria/landing.html")
    return HttpResponse(template.render({}, request))

def not_found_view(request, exception):
    return redirect("memoria:home")
