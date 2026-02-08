from django.apps import apps
from django.utils import timezone
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template import loader


def home(request):
    template = loader.get_template("memoria/home.html")

    if request.method == "POST":
        if not request.user.is_authenticated:
            return redirect("memoria:landing")

        if request.POST.get("action") == "search":
            search_term = request.POST.get("search", "").strip()
            Profile = apps.get_model("users", "User")
            Session = apps.get_model("chat", "Session")
            Memory = apps.get_model("chat", "Memory")
            profile, _ = Profile.objects.get_or_create(user=request.user)
            sessions = Session.objects.filter(user=profile).order_by("-created_at")
            memories = Memory.objects.filter(user=profile).order_by("-updated_at")

            search_results = None
            if search_term:
                search_results = (
                    Session.objects.filter(
                        user=profile,
                        messages__content__icontains=search_term,
                    )
                    .distinct()
                    .order_by("-updated_at")
                )

            context = {
                "username": request.user.username,
                "sessions": sessions,
                "memories": memories,
                "search_results": search_results,
                "search_query": search_term,
            }
            return HttpResponse(template.render(context, request))

        content = request.POST.get("message", "").strip()
        if not content:
            return redirect("memoria:home")
        Profile = apps.get_model("users", "User")
        Session = apps.get_model("chat", "Session")
        profile, _ = Profile.objects.get_or_create(user=request.user)
        session = Session.objects.create(user=profile, title=content[:200])
        Message = apps.get_model("chat", "Message")
        Message.objects.create(session=session, role=2, content=content)
        Message.objects.create(session=session, role=3, content="Agent Response")
        session.updated_at = timezone.now()
        session.save(update_fields=["updated_at"])
        return redirect(session.get_absolute_url())

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
