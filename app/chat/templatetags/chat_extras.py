from datetime import datetime, timedelta

from django import template
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.timesince import timesince
from app.chat.rendering import render_assistant_markdown_html

register = template.Library()


@register.filter
def relative_time(value):
    """Render a timestamp as a relative humanized string.

    Accepts Python ``datetime`` objects, ISO 8601 strings (the form Neo4j
    returns when datetimes are serialized), and ``neo4j.time.DateTime``
    instances. Returns "" on any unparseable input rather than raising,
    because this filter is used in template loops where one bad row should
    not break the whole page."""
    if not value:
        return ""
    if isinstance(value, str):
        # Neo4j may emit nanoseconds (9 fractional digits); Python only
        # accepts up to 6, so trim before parsing.
        candidate = value
        try:
            if "." in candidate and "+" in candidate:
                head, tail = candidate.split("+", 1)
                if "." in head:
                    base, frac = head.split(".", 1)
                    candidate = f"{base}.{frac[:6]}+{tail}"
            value = parse_datetime(candidate)
        except Exception:
            value = None
        if value is None:
            return ""
    if hasattr(value, "to_native"):
        try:
            value = value.to_native()
        except Exception:
            return ""
    if not isinstance(value, datetime):
        return ""
    if value.tzinfo is None:
        value = timezone.make_aware(value, timezone.get_current_timezone())
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


@register.filter(name="smart_cost")
def smart_cost(value):
    try:
        val = float(value or 0)
    except (TypeError, ValueError):
        return "$0.00"
    if val == 0:
        return "$0.00"
    if val < 0.01:
        return f"${val:.4f}"
    return f"${val:.2f}"
