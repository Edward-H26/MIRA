from datetime import timedelta

from django import template
from django.utils import timezone
from django.utils.timesince import timesince
from app.chat.rendering import render_assistant_markdown_html

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


@register.filter(name="assistant_markdown")
def assistant_markdown(value):
    return render_assistant_markdown_html(value)


@register.filter(name="get_vote")
def get_vote(votes_dict, bullet_id):
    if not isinstance(votes_dict, dict):
        return 0
    return votes_dict.get(bullet_id, 0)
