import os
import json
from typing import Any

_client = None

EVENTS = {
    "MESSAGE_SENT": "message:sent",
    "MESSAGE_EDITED": "message:edited",
    "MESSAGE_DELETED": "message:deleted",
    "MEMBER_JOINED": "member:joined",
    "MEMBER_LEFT": "member:left",
    "TYPING": "user:typing",
    "STOP_TYPING": "user:stop-typing",
    "NOTIFICATION": "notification:new",
    "SKILL_GENERATED": "skill:generated",
    "AGENT_UPDATED": "agent:updated",
}


def _get_client():
    global _client
    if _client is not None:
        return _client

    app_id = os.getenv("PUSHER_APP_ID", "")
    key = os.getenv("PUSHER_KEY", "")
    secret = os.getenv("PUSHER_SECRET", "")
    cluster = os.getenv("PUSHER_CLUSTER", "us2")

    if not app_id or not key or not secret:
        return None

    import pusher

    _client = pusher.Pusher(
        app_id=app_id,
        key=key,
        secret=secret,
        cluster=cluster,
        ssl=True,
    )
    return _client


def is_available() -> bool:
    return _get_client() is not None


def get_pusher_key() -> str:
    return os.getenv("PUSHER_KEY", "")


def get_pusher_cluster() -> str:
    return os.getenv("PUSHER_CLUSTER", "us2")


def _channel_for_session(session_id: str | int) -> str:
    return f"group-{session_id}"


def _channel_for_user(user_id: str | int) -> str:
    return f"private-user-{user_id}"


def send_message(session_id: str | int, message: dict) -> bool:
    client = _get_client()
    if client is None:
        return False
    try:
        client.trigger(
            _channel_for_session(session_id),
            EVENTS["MESSAGE_SENT"],
            message,
        )
        return True
    except Exception:
        return False


def send_message_edited(session_id: str | int, message: dict) -> bool:
    client = _get_client()
    if client is None:
        return False
    try:
        client.trigger(
            _channel_for_session(session_id),
            EVENTS["MESSAGE_EDITED"],
            message,
        )
        return True
    except Exception:
        return False


def send_message_deleted(session_id: str | int, message_id: str | int) -> bool:
    client = _get_client()
    if client is None:
        return False
    try:
        client.trigger(
            _channel_for_session(session_id),
            EVENTS["MESSAGE_DELETED"],
            {"messageId": str(message_id)},
        )
        return True
    except Exception:
        return False


def send_typing(session_id: str | int, user_id: str | int, user_name: str) -> bool:
    client = _get_client()
    if client is None:
        return False
    try:
        client.trigger(
            _channel_for_session(session_id),
            EVENTS["TYPING"],
            {"userId": str(user_id), "userName": user_name},
        )
        return True
    except Exception:
        return False


def send_stop_typing(session_id: str | int, user_id: str | int) -> bool:
    client = _get_client()
    if client is None:
        return False
    try:
        client.trigger(
            _channel_for_session(session_id),
            EVENTS["STOP_TYPING"],
            {"userId": str(user_id)},
        )
        return True
    except Exception:
        return False


def send_member_joined(session_id: str | int, agent: dict) -> bool:
    client = _get_client()
    if client is None:
        return False
    try:
        client.trigger(
            _channel_for_session(session_id),
            EVENTS["MEMBER_JOINED"],
            agent,
        )
        return True
    except Exception:
        return False


def send_notification(user_id: str | int, notification: dict) -> bool:
    client = _get_client()
    if client is None:
        return False
    try:
        client.trigger(
            _channel_for_user(user_id),
            EVENTS["NOTIFICATION"],
            notification,
        )
        return True
    except Exception:
        return False


def broadcast_skill_generated(session_id: str | int, skill: dict) -> bool:
    client = _get_client()
    if client is None:
        return False
    try:
        client.trigger(
            _channel_for_session(session_id),
            EVENTS["SKILL_GENERATED"],
            skill,
        )
        return True
    except Exception:
        return False


def authenticate_channel(channel_name: str, socket_id: str) -> dict | None:
    client = _get_client()
    if client is None:
        return None
    try:
        return client.authenticate(channel_name, socket_id)
    except Exception:
        return None
