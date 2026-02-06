from datetime import timedelta

from django import template
from django.utils import timezone
from django.utils.timesince import timesince

register = template.Library()


@register.filter
def relative_time(value):
    if not value:
        return ""
    now = timezone.now()
    delta = now - value
    if delta <= timedelta(days=3):
        return f"{timesince(value, now)} ago"
    return timezone.localtime(value).strftime("%Y-%m-%d")
