from django.urls import path

from . import views

app_name = "chat"
urlpatterns = [
    path("", views.chat_view, name="chat"),
    path("memory/", views.MemoryListView.as_view(), name="memory"),
    path("c/<int:session_id>/", views.ConversationMessagesView.as_view(), name="conversation_detail"),
    path("c/<int:session_id>/rename/", views.session_rename_view, name="session_rename"),
    path("c/<int:session_id>/delete/", views.session_delete_view, name="session_delete"),
    path("m/<int:memory_id>/", views.MemoryBulletsView.as_view(), name="memory_detail"),
    path("analytics/", views.analytics_view, name="analytics"),
    path("analytics/memory-type.png", views.memory_type_chart_png, name="memory_type_chart"),
    path("analytics/memory-strength.png", views.memory_strength_chart_png, name="memory_strength_chart"),
    path("analytics/activity.png", views.activity_chart_png, name="activity_chart"),
    path("api/memories/", views.api_memory_bullets, name="api_memories"),
    path("api/analytics/", views.api_analytics_summary, name="api_analytics"),
    path("api/sessions/", views.SessionAPIView.as_view(), name="api_sessions"),
    path("api/sessions/<int:session_id>/messages/", views.MessageAPIView.as_view(), name="api_messages"),
    path("api/demo/", views.api_demo_response, name="api_demo"),
]
