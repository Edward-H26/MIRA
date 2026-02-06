from django.utils import timezone

from .models import Message
from .models.message import Role


def create_user_message_with_agent_reply(session, content):
    trimmed = (content or "").strip()
    if not trimmed:
        return False

    Message.objects.create(
        session=session,
        role=Role.USER,
        content=trimmed,
    )
    Message.objects.create(
        session=session,
        role=Role.ASSISTANT,
        content="Agent Response",
    )
    session.updated_at = timezone.now()
    session.save(update_fields=["updated_at"])
    return True
