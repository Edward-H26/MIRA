from django.contrib import admin

from .models import Memory, MemoryBullet, Message, Session


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
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
