from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from app.chat.ace_runtime import run_ace_chat_turn
from app.chat.models import Memory, MemoryBullet, Session, Message
from app.chat.models.message import Role
from app.chat.service import get_or_create_profile_for_user


class AceIntegrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="ace_user",
            password="pass12345",
        )
        self.profile = get_or_create_profile_for_user(self.user)
        self.session = Session.objects.create(user=self.profile, title="ACE Test")

    def test_run_ace_chat_turn_updates_memory_and_planner_state(self):
        with patch(
            "app.chat.ace_runtime.generate_reply_text",
            return_value="Use a clear step-by-step explanation. First identify the goal, then provide concrete steps.",
        ):
            result = run_ace_chat_turn(self.session, "How should I plan this project?")

        memory = Memory.objects.get(user=self.profile)

        self.assertIn("answer", result)
        self.assertTrue(result["answer"])
        self.assertGreaterEqual(MemoryBullet.objects.filter(memory=memory).count(), 3)
        self.assertGreater(memory.planner_state.get("total_pulls", 0), 0)
        self.assertGreaterEqual(memory.planner_state.get("total_updates", 0), 1)

    def test_run_ace_chat_turn_falls_back_when_model_empty(self):
        with patch("app.chat.ace_runtime.generate_reply_text", return_value=""):
            result = run_ace_chat_turn(self.session, "Any tips?")

        self.assertIn("couldn't reach the AI service", result["answer"])

    def test_run_ace_chat_turn_includes_recent_conversation_context(self):
        Message.objects.create(session=self.session, role=Role.USER, content="My name is Alex.")
        Message.objects.create(session=self.session, role=Role.ASSISTANT, content="Nice to meet you, Alex.")
        Message.objects.create(session=self.session, role=Role.USER, content="What is my name?")

        captured_prompts = []

        def _capture_prompt(prompt):
            captured_prompts.append(prompt)
            return "Your name is Alex."

        with patch("app.chat.ace_runtime.generate_reply_text", side_effect=_capture_prompt):
            result = run_ace_chat_turn(self.session, "What is my name?")

        self.assertEqual(result["answer"], "Your name is Alex.")
        self.assertTrue(captured_prompts)
        latest_prompt = captured_prompts[0]
        self.assertIn("Recent Conversation", latest_prompt)
        self.assertIn("User: My name is Alex.", latest_prompt)
        self.assertIn("Assistant: Nice to meet you, Alex.", latest_prompt)
        self.assertIn("Latest user question:\nWhat is my name?", latest_prompt)

    def test_run_ace_chat_turn_does_not_store_fact_recall_as_memory_lesson(self):
        Message.objects.create(session=self.session, role=Role.USER, content="My name is Alex.")
        Message.objects.create(session=self.session, role=Role.ASSISTANT, content="Nice to meet you, Alex.")

        with patch("app.chat.ace_runtime.generate_reply_text", return_value="Your name is Alex."):
            run_ace_chat_turn(self.session, "What is my name?")

        memory = Memory.objects.get(user=self.profile)
        learned_bullets = MemoryBullet.objects.filter(memory=memory).exclude(topic="meta_strategy")
        self.assertEqual(learned_bullets.count(), 0)
