from django.contrib import admin

from .models import Payment, Plan, Subscription


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "code", "interval", "price_cents", "currency", "is_active")
    list_filter = ("interval", "is_active", "currency")
    search_fields = ("name", "code", "description")
    ordering = ("name", "code", "interval")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "plan",
        "status",
        "auto_renew",
        "current_period_start",
        "current_period_end",
        "updated_at",
    )
    list_filter = ("status", "auto_renew")
    search_fields = ("user__user__username", "user__user__email", "plan__name", "plan__code")
    list_select_related = ("user", "plan")
    ordering = ("-updated_at",)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "plan",
        "amount_cents",
        "currency",
        "status",
        "paid_at",
        "created_at",
    )
    list_filter = ("status", "currency")
    search_fields = ("user__user__username", "user__user__email", "plan__name", "plan__code")
    list_select_related = ("user", "plan", "subscription")
    ordering = ("-created_at",)
