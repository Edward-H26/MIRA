from django.urls import path

from . import views

app_name = "chat"
urlpatterns = [
    path("", views.chat_view, name="chat"),
    path("memory/", views.memory_view, name="memory"),
    path("c/<int:session_id>/", views.ConversationMessagesView.as_view(), name="conversation_detail"),
    path("m/<int:memory_id>/", views.MemoryBulletsView.as_view(), name="memory_detail"),
]
