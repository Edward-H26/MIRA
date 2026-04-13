from django.contrib import admin
from django.http import JsonResponse
from django.urls import path

from .models import Memory, MemoryBullet, Message, Session, Agent, SessionParticipant, AuditLog, Notification, RequestLog


class Neo4jDataBrowserAdmin(admin.ModelAdmin):
    class Meta:
        app_label = "chat"

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path("neo4j/agents/", self.admin_site.admin_view(self._neo4j_agents), name="neo4j_agents"),
            path("neo4j/sessions/", self.admin_site.admin_view(self._neo4j_sessions), name="neo4j_sessions"),
            path("neo4j/stats/", self.admin_site.admin_view(self._neo4j_stats), name="neo4j_stats"),
        ]
        return custom + urls

    @staticmethod
    def _neo4j_agents(request):
        from app.services import neo4j_memory as neo4j
        userId = request.GET.get("user_id", "")
        if not userId:
            return JsonResponse({"error": "user_id required"}, status=400)
        agents = neo4j.get_agents_for_user(userId)
        return JsonResponse({"count": len(agents), "agents": agents})

    @staticmethod
    def _neo4j_sessions(request):
        from app.services import neo4j_memory as neo4j
        userId = request.GET.get("user_id", "")
        if not userId:
            return JsonResponse({"error": "user_id required"}, status=400)
        sessions = neo4j.get_sessions_for_user(userId)
        return JsonResponse({"count": len(sessions), "sessions": sessions})

    @staticmethod
    def _neo4j_stats(request):
        from app.services import neo4j_memory as neo4j
        userId = request.GET.get("user_id", "")
        if not userId:
            return JsonResponse({"error": "user_id required"}, status=400)
        stats = neo4j.aggregate_request_stats(userId, days=30)
        return JsonResponse(stats)


@admin.register(Session)
class SessionAdmin(Neo4jDataBrowserAdmin):
    list_display = ("id", "user", "title", "created_at", "updated_at")
    search_fields = ("user__user__username", "user__user__email", "title")
    list_select_related = ("user",)
    ordering = ("-updated_at",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "role", "created_at")
    list_filter = ("role",)
    search_fields = ("session__user__user__username", "session__user__user__email", "content")
    list_select_related = ("session", "session__user")
    ordering = ("-created_at",)


@admin.register(Memory)
class MemoryAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "access_clock", "created_at", "updated_at")
    search_fields = ("user__user__username", "user__user__email")
    list_select_related = ("user",)
    ordering = ("-updated_at",)


@admin.register(MemoryBullet)
class MemoryBulletAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "memory",
        "memory_type",
        "topic",
        "helpful_count",
        "harmful_count",
        "strength",
        "last_accessed",
    )
    list_filter = ("memory_type",)
    search_fields = ("topic", "content", "concept")
    list_select_related = ("memory", "memory__user")
    ordering = ("-last_accessed",)


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "user", "is_active", "temperature", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "description", "user__user__username")
    list_select_related = ("user",)
    ordering = ("-created_at",)


@admin.register(SessionParticipant)
class SessionParticipantAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "agent", "joined_at")
    search_fields = ("session__title", "agent__name")
    list_select_related = ("session", "agent")
    ordering = ("-joined_at",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "agent", "event_type", "created_at")
    list_filter = ("event_type",)
    search_fields = ("user__user__username", "event_type", "description")
    list_select_related = ("user", "agent")
    ordering = ("-created_at",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "title", "notification_type", "is_read", "created_at")
    list_filter = ("notification_type", "is_read")
    search_fields = ("user__user__username", "title", "message")
    list_select_related = ("user",)
    ordering = ("-created_at",)


@admin.register(RequestLog)
class RequestLogAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "request_type", "model_name", "status", "latency_ms", "total_tokens", "estimated_cost_usd", "created_at")
    list_filter = ("status", "model_name", "request_type")
    search_fields = ("user__user__username", "model_name", "error_type")
    list_select_related = ("user",)
    ordering = ("-created_at",)
