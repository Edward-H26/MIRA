from django.contrib import admin

from .models import UserProfile


@admin.register(UserProfile)
class UserAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "profile_img")
    search_fields = ("user__username", "user__email")
    list_select_related = ("user",)
