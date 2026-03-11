from unittest.mock import patch
import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from app.chat.models import Message, Session
from app.chat.models.message import Role
from app.chat.service import (
    get_or_create_profile_for_user,
    stream_user_message_with_agent_reply,
)


class ChatStreamingServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="stream_service_user",
            password="pass12345",
        )
        self.profile = get_or_create_profile_for_user(self.user)
        self.session = Session.objects.create(user=self.profile, title="Streaming Test")

    def test_stream_user_message_with_agent_reply_saves_final_message(self):
        with patch(
            "app.chat.service.run_ace_chat_turn",
            return_value={"answer": "Hello world"},
        ):
            events = list(stream_user_message_with_agent_reply(self.session, "Hi there"))

        self.assertEqual(events[0]["type"], "delta")
        self.assertEqual(events[0]["content"], "Hello")
        self.assertIn("Hello", events[0]["html"])
        self.assertEqual(events[1]["type"], "delta")
        self.assertEqual(events[1]["content"], " world")
        self.assertIn("Hello world", events[1]["html"])
        self.assertEqual(events[2]["type"], "done")
        self.assertEqual(events[2]["message_id"], Message.objects.latest("id").id)
        self.assertEqual(events[2]["content"], "Hello world")
        self.assertIn("Hello world", events[2]["html"])

        saved_messages = list(self.session.messages.order_by("created_at"))
        self.assertEqual(len(saved_messages), 2)
        self.assertEqual(saved_messages[0].role, Role.USER)
        self.assertEqual(saved_messages[0].content, "Hi there")
        self.assertEqual(saved_messages[1].role, Role.ASSISTANT)
        self.assertEqual(saved_messages[1].content, "Hello world")

    def test_stream_user_message_with_agent_reply_uses_fallback_on_failure(self):
        with patch(
            "app.chat.service.run_ace_chat_turn",
            side_effect=RuntimeError("ACE unavailable"),
        ):
            events = list(stream_user_message_with_agent_reply(self.session, "Hi there"))

        self.assertEqual(events[0]["type"], "delta")
        self.assertIn("couldn't reach the AI service", events[0]["content"])
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["content"], events[0]["content"])


class ChatStreamingViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="stream_view_user",
            password="pass12345",
        )
        self.profile = get_or_create_profile_for_user(self.user)
        self.session = Session.objects.create(user=self.profile, title="Streaming View Test")
        self.client.force_login(self.user)

    def test_conversation_detail_post_returns_ndjson_chunks_for_ajax(self):
        with patch(
            "app.chat.views.stream_user_message_with_agent_reply",
            return_value=iter(
                [
                    {"type": "delta", "content": "Hello", "html": "<p>Hello</p>"},
                    {"type": "done", "content": "Hello", "message_id": 1, "html": "<p>Hello</p>"},
                ]
            ),
        ):
            response = self.client.post(
                reverse("chat:conversation_detail", args=[self.session.pk]),
                {"message": "Hi"},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        payloads = [
            json.loads(chunk)
            for chunk in (
                part.decode("utf-8") if isinstance(part, bytes) else part
                for part in response.streaming_content
            )
            if chunk.strip()
        ]

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("application/x-ndjson"))
        self.assertEqual(payloads[0], {"type": "delta", "content": "Hello", "html": "<p>Hello</p>"})
        self.assertEqual(payloads[1], {"type": "done", "content": "Hello", "message_id": 1, "html": "<p>Hello</p>"})

    def test_conversation_detail_post_rejects_empty_messages(self):
        response = self.client.post(
            reverse("chat:conversation_detail", args=[self.session.pk]),
            {"message": "   "},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Empty message")

    def test_conversation_detail_post_rejects_when_generation_in_progress(self):
        self.session.generation_in_progress = True
        self.session.save(update_fields=["generation_in_progress"])

        response = self.client.post(
            reverse("chat:conversation_detail", args=[self.session.pk]),
            {"message": "Second message"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "generation_in_progress")

    def test_home_post_returns_redirect_url_for_immediate_navigation(self):
        response = self.client.post(
            reverse("memoria:home"),
            {"message": "Start a new chat"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        payload = response.json()
        created_session = Session.objects.get(pk=payload["session_id"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["redirect_url"], created_session.get_absolute_url())
        self.assertEqual(
            self.client.session["pending_chat_prompts"][str(created_session.pk)],
            "Start a new chat",
        )

    def test_conversation_detail_get_reads_pending_prompt_from_session(self):
        self.client.session["pending_chat_prompts"] = {str(self.session.pk): "Auto send me"}
        self.client.session.save()

        response = self.client.get(reverse("chat:conversation_detail", args=[self.session.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-pending-prompt="Auto send me"', html=False)
        self.assertNotIn("pending_chat_prompts", self.client.session)

    def test_conversation_lock_status_view_returns_generation_state(self):
        self.session.generation_in_progress = True
        self.session.save(update_fields=["generation_in_progress"])

        response = self.client.get(reverse("chat:conversation_lock_status", args=[self.session.pk]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["session_id"], self.session.pk)
        self.assertTrue(payload["generation_in_progress"])

    def test_conversation_lock_wait_view_returns_unlocked_state_when_lock_is_stale(self):
        self.session.generation_in_progress = True
        self.session.generation_started_at = timezone.now() - timedelta(minutes=10)
        self.session.save(update_fields=["generation_in_progress", "generation_started_at"])

        response = self.client.get(reverse("chat:conversation_lock_wait", args=[self.session.pk]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["session_id"], self.session.pk)
        self.assertFalse(payload["generation_in_progress"])
        self.assertFalse(payload["timed_out"])
