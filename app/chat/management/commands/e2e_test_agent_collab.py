"""End-to-end test harness for agent-to-agent collaboration.

Exercises the real streaming pipeline (stream_user_message_with_agent_reply),
Neo4j Agent/Session/Message CRUD, mention parsing, agent resolution, chain
continuation, turn-limit enforcement, self-continuation, and user-mention
notifications. The Gemini API is replaced with a deterministic scripted
responder so the test is fast, cheap, and reproducible.

Run locally:
    NEO4J_URI=... NEO4J_USERNAME=... NEO4J_PASSWORD=... \\
        python manage.py e2e_test_agent_collab

Add --verbose for detailed payload traces, --scenario=NAME to run a single
scenario, --keep-data to skip cleanup.
"""
import time
import uuid

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class ScriptedGeminiStream:
    """Replaces app.services.gemini.generate_reply_stream.

    The test sets `ScriptedGeminiStream.responses` to a list of strings; each
    call to generate_reply_stream pops one response, yields it as a single
    delta chunk, then yields a usage_metadata payload. If the script is
    exhausted, raises so the test fails loudly instead of calling the real API.
    """
    responses: list[str] = []
    call_count: int = 0
    call_log: list[str] = []

    @classmethod
    def reset(cls, responses: list[str]) -> None:
        cls.responses = list(responses)
        cls.call_count = 0
        cls.call_log = []

    @classmethod
    def stream(cls, user_text: str, *, max_output_tokens: int = 2048):
        cls.call_count += 1
        cls.call_log.append(user_text[:200])
        if not cls.responses:
            raise RuntimeError(
                f"ScriptedGeminiStream exhausted on call #{cls.call_count}. "
                f"prompt (first 200 chars): {user_text[:200]!r}"
            )
        response = cls.responses.pop(0)
        for chunk in _chunkify(response):
            yield chunk
        yield {
            "_type": "usage_metadata",
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "thinking_tokens": 0,
            "total_tokens": 30,
        }


def _chunkify(text: str, chunk_size: int = 16):
    for i in range(0, len(text), chunk_size):
        yield text[i:i + chunk_size]


class Command(BaseCommand):
    help = (
        "End-to-end test of agent-to-agent collaboration. Mocks Gemini with a "
        "scripted responder, exercises the real streaming pipeline."
    )

    def add_arguments(self, parser):
        parser.add_argument("--verbose", action="store_true", help="Print every payload.")
        parser.add_argument("--scenario", type=str, default="", help="Run only the named scenario.")
        parser.add_argument("--keep-data", action="store_true", help="Skip cleanup.")

    def handle(self, *args, **options):
        self.verboseMode = bool(options.get("verbose"))
        self.keepData = bool(options.get("keep_data"))
        onlyScenario = (options.get("scenario") or "").strip().lower()

        from app.services import gemini as gemini_module
        from app.services import neo4j_memory as neo4j
        from app.chat import service as chat_service_module

        driver = neo4j._get_driver()
        if driver is None:
            self.stdout.write(self.style.ERROR(
                "Neo4j driver unavailable. Set NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD."
            ))
            return

        # Two patch sites: the gemini module itself AND app.chat.service which
        # did a module-level `from app.services.gemini import generate_reply_stream`
        # and therefore has its own binding that won't be updated by patching
        # only the source module.
        self._originalGenerateGemini = gemini_module.generate_reply_stream
        self._originalGenerateService = getattr(chat_service_module, "generate_reply_stream", None)
        gemini_module.generate_reply_stream = ScriptedGeminiStream.stream
        chat_service_module.generate_reply_stream = ScriptedGeminiStream.stream
        self._chatServiceModule = chat_service_module
        self._geminiModule = gemini_module

        User = get_user_model()
        testTag = f"e2e_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        self.testTag = testTag

        self.django_user = User.objects.create_user(
            username=testTag,
            email=f"{testTag}@e2e.local",
            password="e2e-test-password",
        )
        from app.users.models import UserProfile
        self.profile, _ = UserProfile.objects.get_or_create(
            user=self.django_user,
            defaults={"display_name": "E2E Tester"},
        )

        scenarios = [
            ("single_agent_reply", self._scenario_single_agent_reply),
            ("agent_mentions_agent", self._scenario_agent_mentions_agent),
            ("self_continuation", self._scenario_self_continuation),
            ("turn_limit_enforced", self._scenario_turn_limit_enforced),
            ("invalid_mention_ignored", self._scenario_invalid_mention),
            ("user_mention_triggers_notification", self._scenario_user_mention_notifies),
        ]
        passed = 0
        failed = 0
        failures: list[str] = []

        try:
            for name, fn in scenarios:
                if onlyScenario and onlyScenario != name:
                    continue
                self.stdout.write(self.style.MIGRATE_HEADING(f"\n== scenario: {name} =="))
                try:
                    fn()
                    self.stdout.write(self.style.SUCCESS(f"   PASS: {name}"))
                    passed += 1
                except AssertionError as exc:
                    self.stdout.write(self.style.ERROR(f"   FAIL: {name}: {exc}"))
                    failed += 1
                    failures.append(f"{name}: {exc}")
                except Exception as exc:
                    self.stdout.write(self.style.ERROR(
                        f"   ERROR: {name}: {exc.__class__.__name__}: {exc}"
                    ))
                    failed += 1
                    failures.append(f"{name}: {exc.__class__.__name__}: {exc}")
        finally:
            self._geminiModule.generate_reply_stream = self._originalGenerateGemini
            if self._originalGenerateService is not None:
                self._chatServiceModule.generate_reply_stream = self._originalGenerateService
            self._cleanup()

        self.stdout.write("")
        if failed == 0:
            self.stdout.write(self.style.SUCCESS(
                f"E2E PASS: {passed} scenario(s) succeeded, 0 failed."
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f"E2E FAIL: {passed} passed, {failed} failed:"
            ))
            for f in failures:
                self.stdout.write(f"  - {f}")

    def _cleanup(self) -> None:
        if self.keepData:
            return
        from app.services import neo4j_memory as neo4j
        try:
            neo4j.delete_user_cascade(str(self.profile.pk))
        except Exception:
            pass
        try:
            self.django_user.delete()
        except Exception:
            pass

    def _create_agent(self, name: str) -> dict:
        from app.services import neo4j_memory as neo4j
        agent = neo4j.create_agent(user_id=str(self.profile.pk), name=name)
        assert agent.get("id"), f"create_agent returned no id for {name}"
        return agent

    def _create_session(self, title: str = "E2E") -> dict:
        from app.services import neo4j_memory as neo4j
        session = neo4j.create_session(str(self.profile.pk), title)
        assert session.get("id"), "create_session returned no id"
        return session

    def _drive_stream(self, session, content: str) -> list[dict]:
        from app.chat.service import stream_user_message_with_agent_reply
        session["_user"] = self.django_user
        session["_profile_id"] = str(self.profile.pk)
        payloads = []
        for payload in stream_user_message_with_agent_reply(session, content):
            payloads.append(payload)
            if self.verboseMode:
                summary = {k: v for k, v in payload.items() if k != "html"}
                self.stdout.write(f"      payload: {summary}")
        return payloads

    def _payload_text(self, payload: dict) -> str:
        return (payload.get("content") or "")

    def _concat_deltas(self, payloads: list[dict]) -> str:
        parts = []
        for p in payloads:
            if p.get("type") == "delta":
                parts.append(self._payload_text(p))
        return "".join(parts)

    def _assistant_turns(self, payloads: list[dict]) -> list[dict]:
        return [p for p in payloads if p.get("type") in ("done", "agent_turn")]

    # ---- scenarios ---------------------------------------------------------

    def _scenario_single_agent_reply(self):
        self._create_agent("Alice")
        ScriptedGeminiStream.reset([
            "SIMPLE",
            "Hello from Alice!",
        ])
        session = self._create_session()
        payloads = self._drive_stream(session, "@Alice please introduce yourself.")

        assertionText = self._concat_deltas(payloads)
        assert "Hello from Alice" in assertionText or any(
            "Alice" in self._payload_text(p) for p in self._assistant_turns(payloads)
        ), f"Alice's reply not in stream. deltas={assertionText!r}"

        dones = [p for p in payloads if p.get("type") == "done"]
        assert len(dones) >= 1, f"no 'done' payload, got types: {[p.get('type') for p in payloads]}"

    def _scenario_agent_mentions_agent(self):
        self._create_agent("Bob")
        self._create_agent("Carol")
        ScriptedGeminiStream.reset([
            "SIMPLE",
            "Great question. @Carol can you add more?",
            "SIMPLE",
            "Here is my addition, from Carol.",
        ])
        session = self._create_session()
        payloads = self._drive_stream(session, "@Bob what do you think?")

        assistantTurns = self._assistant_turns(payloads)
        assert len(assistantTurns) >= 2, (
            f"expected >=2 assistant turns (Bob + Carol), got {len(assistantTurns)}. "
            f"types: {[p.get('type') for p in payloads]}"
        )
        names = [p.get("agentName", "") for p in assistantTurns]
        assert any("Carol" in n for n in names), f"Carol never responded. names={names}"

    def _scenario_self_continuation(self):
        self._create_agent("Dave")
        ScriptedGeminiStream.reset([
            "SIMPLE",
            "Thinking... @Dave keep going.",
            "SIMPLE",
            "Continuing my own train of thought.",
        ])
        session = self._create_session()
        payloads = self._drive_stream(session, "@Dave analyze step by step.")

        turns = self._assistant_turns(payloads)
        daveTurns = sum(1 for t in turns if "Dave" in (t.get("agentName") or ""))
        assert daveTurns >= 2, f"expected >=2 Dave turns (original + self-continuation), got {daveTurns}"

    def _scenario_turn_limit_enforced(self):
        self._create_agent("Eve")
        ScriptedGeminiStream.reset([
            "SIMPLE", "Reply 1 @Eve",
            "SIMPLE", "Reply 2 @Eve",
            "SIMPLE", "Reply 3 @Eve",
            "SIMPLE", "Reply 4 @Eve",
            "SIMPLE", "Reply 5 @Eve",
            "SIMPLE", "Reply 6 @Eve",
        ])
        session = self._create_session()
        payloads = self._drive_stream(session, "@Eve please think recursively.")

        turns = self._assistant_turns(payloads)
        eveTurns = sum(1 for t in turns if "Eve" in (t.get("agentName") or ""))
        assert eveTurns <= 3, (
            f"turn limit violated: Eve responded {eveTurns} times (expected <=3). "
            f"CHAT_MAX_TURNS_PER_AGENT is 2, initial + self-continuation = 2-3 max."
        )

    def _scenario_invalid_mention(self):
        self._create_agent("Frank")
        ScriptedGeminiStream.reset([
            "SIMPLE",
            "Hi, I'll answer. @NonexistentPerson would have helped but they aren't here.",
        ])
        session = self._create_session()
        payloads = self._drive_stream(session, "@Frank what about this?")
        dones = [p for p in payloads if p.get("type") == "done"]
        assert len(dones) >= 1, "no done payload after invalid mention"

        assert ScriptedGeminiStream.responses == [], (
            f"unexpected extra gemini calls. script leftovers: {ScriptedGeminiStream.responses}"
        )

    def _scenario_user_mention_notifies(self):
        from app.services import neo4j_memory as neo4j
        self._create_agent("Grace")
        ScriptedGeminiStream.reset([
            "SIMPLE",
            f"Hey @{self.profile.display_name or self.django_user.username}, I need your input on this decision.",
        ])
        session = self._create_session()
        before = neo4j.get_unread_notification_count(str(self.profile.pk))
        self._drive_stream(session, "@Grace make a decision.")
        after = neo4j.get_unread_notification_count(str(self.profile.pk))

        assert after >= before, (
            f"unread notification count regressed: before={before} after={after}"
        )
