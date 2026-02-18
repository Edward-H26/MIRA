from django.urls import path

from . import api, views

app_name = "chat"
urlpatterns = [
    path("memory/", views.MemoryListView.as_view(), name="memory"),
    path("c/<int:session_id>/", views.ConversationMessagesView.as_view(), name="conversation_detail"),
    path("c/<int:session_id>/rename/", views.session_rename_view, name="session_rename"),
    path("c/<int:session_id>/delete/", views.session_delete_view, name="session_delete"),
    path("m/<int:memory_id>/", views.MemoryBulletsView.as_view(), name="memory_detail"),
    path("analytics/", views.analytics_view, name="analytics"),
    path("analytics/memory-type.png", views.memory_type_chart_png, name="memory_type_chart"),
    path("analytics/memory-strength.png", views.memory_strength_chart_png, name="memory_strength_chart"),
    path("analytics/activity.png", views.activity_chart_png, name="activity_chart"),
    path("analytics/export/sessions/", views.export_sessions_report, name="export_sessions_report"),
    path("analytics/export/memory-bullets/", views.export_memory_bullets_report, name="export_memory_bullets_report"),
    path(
        "charts/active-users/",
        views.vega_daily_users_chart_view,
        name="charts_active_users",
    ),
    path(
        "charts/messages/",
        views.vega_daily_messages_chart_view,
        name="charts_messages",
    ),
    path("api/memories/", api.api_memory_bullets, name="api_memories"),
    path("api/analytics/", api.api_analytics_summary, name="api_analytics"),
    path("api/sessions/", api.SessionAPIView.as_view(), name="api_sessions"),
    path("api/sessions/<int:session_id>/messages/", api.MessageAPIView.as_view(), name="api_messages"),
    path("api/active-users/", api.api_public_daily_active_users, name="api_active_users"),
    path(
        "api/active-users/holidays/",
        api.api_public_daily_active_users_with_holidays,
        name="api_active_users_holidays",
    ),
]
