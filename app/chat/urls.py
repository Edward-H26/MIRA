from django.urls import path

from . import api, views

app_name = "chat"

page_urlpatterns = [
    path("memory/", views.MemoryListView.as_view(), name="memory"),
    path("c/<int:session_id>/", views.ConversationMessagesView.as_view(), name="conversation_detail"),
    path("c/<int:session_id>/lock-status/", views.conversation_lock_status_view, name="conversation_lock_status"),
    path("c/<int:session_id>/lock-wait/", views.conversation_wait_for_unlock_view, name="conversation_lock_wait"),
    path("c/<int:session_id>/rename/", views.session_rename_view, name="session_rename"),
    path("c/<int:session_id>/delete/", views.session_delete_view, name="session_delete"),
    path("c/<int:session_id>/typing/", views.typing_view, name="typing"),
    path("c/<int:session_id>/stop-typing/", views.stop_typing_view, name="stop_typing"),
    path("c/<int:session_id>/upload/", views.conversation_upload_view, name="conversation_upload"),
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
    path("agents/", views.agent_list_view, name="agent_list"),
    path("agents/marketplace/", views.agent_marketplace_view, name="agent_marketplace"),
    path("agents/marketplace/<str:template_id>/", views.agent_marketplace_detail_view, name="agent_marketplace_detail"),
    path("agents/marketplace/<str:template_id>/install/", views.agent_template_install_view, name="agent_template_install"),
    path("agents/<str:agent_id>/", views.agent_detail_view, name="agent_detail"),
    path("agents/<str:agent_id>/delete/", views.agent_delete_view, name="agent_delete"),
    path("agents/<str:agent_id>/settings/", views.agent_settings_view, name="agent_settings"),
    path("agents/<str:agent_id>/skills/", views.agent_skills_view, name="agent_skills"),
    path("skills/<int:bullet_id>/toggle/", views.skill_toggle_view, name="skill_toggle"),
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("activity/", views.activity_log_view, name="activity_log"),
    path("settings/admin/", views.admin_settings_view, name="admin_settings"),
    path("document/upload/", views.document_upload_view, name="document_upload"),
    path("groups/", views.group_list_view, name="group_list"),
    path("groups/create/", views.group_create_view, name="group_create"),
    path("groups/join/", views.group_join_view, name="group_join"),
    path("groups/<int:session_id>/leave/", views.group_leave_view, name="group_leave"),
    path("skills/marketplace/", views.skill_marketplace_view, name="skill_marketplace"),
    path("skills/marketplace/<str:skill_id>/", views.skill_marketplace_detail_view, name="skill_marketplace_detail"),
    path("skills/marketplace/<str:skill_id>/install/", views.skill_install_view, name="skill_install"),
    path("notifications/mark-read/<str:notification_id>/", views.notification_mark_read_view, name="notification_mark_read"),
    path("notifications/mark-all-read/", views.notification_mark_all_read_view, name="notification_mark_all_read"),
]

api_urlpatterns = [
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
    path("api/pusher/auth/", views.pusher_auth_view, name="pusher_auth"),
    path("api/agents/", api.api_agents, name="api_agents"),
    path("api/agents/<str:agent_id>/skills/", api.api_agent_skills, name="api_agent_skills"),
    path("api/notifications/", api.api_notifications, name="api_notifications"),
    path("api/activity/", api.api_activity_feed, name="api_activity_feed"),
    path("api/semantic-search/", api.api_semantic_search, name="api_semantic_search"),
]

urlpatterns = page_urlpatterns + api_urlpatterns
