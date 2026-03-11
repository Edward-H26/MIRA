import json
import logging
import re

from django.conf import settings

SINK_LOGGER_NAME = "event_log_sink"
LOGGER_NAME_PATTERN = re.compile(r"[^a-zA-Z0-9_]+")


def is_dev_event_log_enabled():
    return bool(getattr(settings, "ENABLE_DEV_EVENT_LOG", False))


def _safe_event_name(event):
    value = (event or "").strip()
    return value or "unknown_event"


def _safe_logger_name(event_name):
    normalized = LOGGER_NAME_PATTERN.sub("_", event_name).strip("_")
    return normalized or "unknown_event"


def _get_event_logger(event_name):
    sink_logger = logging.getLogger(SINK_LOGGER_NAME)
    event_logger_name = _safe_logger_name(event_name)
    event_logger = logging.getLogger(event_logger_name)

    if not event_logger.handlers:
        for handler in sink_logger.handlers:
            event_logger.addHandler(handler)
        event_logger.setLevel(sink_logger.level or logging.INFO)
        event_logger.propagate = False
    return event_logger


def log_event(event, request=None, **fields):
    if not is_dev_event_log_enabled():
        return

    event_name = _safe_event_name(event)
    payload = {"event": event_name}
    if request is not None:
        user_id = None
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            user_id = user.id
        payload.update(
            {
                "method": getattr(request, "method", ""),
                "path": getattr(request, "path", ""),
                "user_id": user_id,
                "remote_addr": request.META.get("REMOTE_ADDR"),
            }
        )
    for key, value in fields.items():
        if value is not None:
            payload[key] = value

    logger = _get_event_logger(event_name)
    logger.info(json.dumps(payload, ensure_ascii=False))
