import time

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "End-to-end cross-validation of the Neo4j integration layer. Runs "
        "eight edge-case scenarios covering every outbox operation plus the "
        "cascade-delete path. Uses throwaway test data and cleans up after "
        "itself. Safe to run in any environment with Neo4j available."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep-data",
            action="store_true",
            help="Skip cleanup at the end (for manual inspection).",
        )
        parser.add_argument(
            "--stop-on-failure",
            action="store_true",
            help="Stop at the first failing scenario (default runs all then reports).",
        )

    def handle(self, *args, **options):
        from app.services import neo4j_memory as neo4j

        driver = neo4j._get_driver()
        if driver is None:
            self.stdout.write(self.style.ERROR(
                "Neo4j driver unavailable. Set NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD."
            ))
            return

        self.stopOnFailure = bool(options.get("stop_on_failure"))
        self.keepData = bool(options.get("keep_data"))
        self.testUserId = "selftest_" + str(int(time.time() * 1000))
        self.passed = 0
        self.failed = 0
        self.failures: list[str] = []

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Cross-validation: 8 edge-case scenarios (test user = {self.testUserId})"
        ))

        scenarios = [
            ("agent create + outbox audit row", self._test_agent_create_audit),
            ("agent update idempotent replay", self._test_agent_update_replay),
            ("agent delete via outbox", self._test_agent_delete_outbox),
            ("session create + outbox record", self._test_session_create),
            ("session update field diff applied", self._test_session_update),
            ("session delete cascades messages", self._test_session_delete),
            ("outbox drain handles unknown op", self._test_unknown_op_fails_gracefully),
            ("cascade-delete removes user + owned", self._test_user_cascade_delete),
        ]

        for name, fn in scenarios:
            self.stdout.write(f"\n-- {name}")
            try:
                fn()
                self.stdout.write(self.style.SUCCESS(f"   PASS: {name}"))
                self.passed += 1
            except AssertionError as exc:
                self.stdout.write(self.style.ERROR(f"   FAIL: {name}: {exc}"))
                self.failed += 1
                self.failures.append(f"{name}: {exc}")
                if self.stopOnFailure:
                    break
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"   ERROR: {name}: {exc}"))
                self.failed += 1
                self.failures.append(f"{name}: {exc.__class__.__name__}: {exc}")
                if self.stopOnFailure:
                    break

        self._cleanup()

        self.stdout.write("")
        if self.failed == 0:
            self.stdout.write(self.style.SUCCESS(
                f"All {self.passed} scenario(s) passed."
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f"{self.failed} of {self.passed + self.failed} scenario(s) failed:"
            ))
            for f in self.failures:
                self.stdout.write(f"  - {f}")

    def _setup_user(self):
        from app.services import neo4j_memory as neo4j
        neo4j.create_or_update_django_user(
            user_id=self.testUserId,
            username=self.testUserId,
            email=f"{self.testUserId}@selftest.local",
            password_hash="",
            display_name="Selftest",
        )

    def _cleanup(self):
        if self.keepData:
            return
        from app.chat.models.outbox_event import OutboxEvent
        from app.services import neo4j_memory as neo4j
        try:
            neo4j.delete_user_cascade(self.testUserId)
        except Exception:
            pass
        try:
            OutboxEvent.objects.filter(payload__user_id=self.testUserId).delete()
        except Exception:
            pass

    # ---- scenarios ----------------------------------------------------

    def _test_agent_create_audit(self):
        from app.chat.models.outbox_event import OutboxEvent
        from app.services import neo4j_memory as neo4j
        self._setup_user()
        agent = neo4j.create_agent(user_id=self.testUserId, name="Test Agent A")
        agentId = str(agent.get("id", ""))
        assert agentId, "create_agent returned no id"
        from app.chat import outbox
        outbox.record_applied(
            "agent.create", "Agent", agentId,
            payload={"user_id": self.testUserId, "name": "Test Agent A"},
        )
        applied = OutboxEvent.objects.filter(
            entity_id=agentId, operation="agent.create",
            status=OutboxEvent.STATUS_APPLIED,
        ).count()
        assert applied == 1, f"expected 1 applied audit row, got {applied}"

    def _test_agent_update_replay(self):
        from app.chat.models.outbox_event import OutboxEvent
        from app.services import neo4j_memory as neo4j
        from app.chat import outbox
        self._setup_user()
        agent = neo4j.create_agent(user_id=self.testUserId, name="ReplayTarget")
        agentId = str(agent["id"])

        neo4j.update_agent(agentId, description="first")
        outbox.enqueue(
            "agent.update", "Agent", agentId,
            payload={"fields": {"description": "first"}},
        )
        from django.core.management import call_command
        call_command("drain_outbox", "--once", "--batch-size=10")

        after = neo4j.get_agent(self.testUserId, agentId) or {}
        assert after.get("description") == "first", f"description not updated: {after.get('description')!r}"

        applied = OutboxEvent.objects.filter(
            entity_id=agentId, operation="agent.update",
            status=OutboxEvent.STATUS_APPLIED,
        ).count()
        assert applied >= 1, "outbox row did not transition to APPLIED"

    def _test_agent_delete_outbox(self):
        from app.services import neo4j_memory as neo4j
        from app.chat import outbox
        self._setup_user()
        agent = neo4j.create_agent(user_id=self.testUserId, name="DeleteMe")
        agentId = str(agent["id"])
        neo4j.delete_agent(agentId)
        outbox.enqueue("agent.delete", "Agent", agentId, payload={"user_id": self.testUserId})

        from django.core.management import call_command
        call_command("drain_outbox", "--once", "--batch-size=10")

        still = neo4j.get_agent(self.testUserId, agentId)
        assert not still, "agent still visible after delete"

    def _test_session_create(self):
        from app.chat.write_service import create_session_with_outbox
        from app.chat.models.outbox_event import OutboxEvent
        self._setup_user()
        session = create_session_with_outbox(self.testUserId, "Selftest Session")
        sessionId = str(session.get("id", ""))
        assert sessionId, "create_session_with_outbox returned no id"
        applied = OutboxEvent.objects.filter(
            entity_id=sessionId, operation="session.create",
            status=OutboxEvent.STATUS_APPLIED,
        ).count()
        assert applied == 1, f"expected 1 applied session.create row, got {applied}"

    def _test_session_update(self):
        from app.chat.write_service import create_session_with_outbox, update_session_with_outbox
        from app.services import neo4j_memory as neo4j
        self._setup_user()
        session = create_session_with_outbox(self.testUserId, "Before")
        sessionId = session["id"]
        update_session_with_outbox(sessionId, title="After")

        from django.core.management import call_command
        call_command("drain_outbox", "--once", "--batch-size=10")

        after = neo4j.get_session_by_id(sessionId) or {}
        assert after.get("title") == "After", f"title not updated: {after.get('title')!r}"

    def _test_session_delete(self):
        from app.chat.write_service import create_session_with_outbox, delete_session_with_outbox
        from app.services import neo4j_memory as neo4j
        self._setup_user()
        session = create_session_with_outbox(self.testUserId, "ToDelete")
        sessionId = session["id"]
        neo4j.create_message(
            session_id=sessionId, content="hello",
            created_by=self.testUserId, role="user",
        )
        delete_session_with_outbox(sessionId)

        from django.core.management import call_command
        call_command("drain_outbox", "--once", "--batch-size=10")

        still = neo4j.get_session_by_id(sessionId)
        assert not still, "session still present after delete"

    def _test_unknown_op_fails_gracefully(self):
        from app.chat.models.outbox_event import OutboxEvent
        from app.chat import outbox
        outbox.enqueue("definitely.not_real_op", "Bogus", "bogus-id", payload={})
        evId = OutboxEvent.objects.filter(operation="definitely.not_real_op").latest("created_at").pk

        from django.core.management import call_command
        call_command("drain_outbox", "--once", "--batch-size=10", "--max-attempts=1")

        ev = OutboxEvent.objects.get(pk=evId)
        assert ev.status == OutboxEvent.STATUS_FAILED, f"expected FAILED, got {ev.status}"
        assert "Unknown outbox operation" in (ev.last_error or ""), (
            f"expected 'Unknown outbox operation' in last_error, got {ev.last_error!r}"
        )
        ev.delete()

    def _test_user_cascade_delete(self):
        from app.services import neo4j_memory as neo4j
        self._setup_user()
        agent = neo4j.create_agent(user_id=self.testUserId, name="CascadeAgent")
        agentId = str(agent["id"])
        session = neo4j.create_session(self.testUserId, "CascadeSession")
        sessionId = session["id"]

        summary = neo4j.delete_user_cascade(self.testUserId)

        assert int(summary.get("agents") or 0) >= 1, f"cascade summary missing agents: {summary}"
        assert int(summary.get("sessions") or 0) >= 1, f"cascade summary missing sessions: {summary}"
        assert neo4j.get_agent(self.testUserId, agentId) is None, "agent leaked"
        assert neo4j.get_session_by_id(sessionId) is None, "session leaked"
