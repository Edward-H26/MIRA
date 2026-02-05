from django.shortcuts import render

def home(request):
    return render(request, "chat.html")

def chat(request):
    return render(request, "chat.html")

def memory(request):
    return render(request, "memory.html")

def profile(request):
    return render(request, "profile.html")
