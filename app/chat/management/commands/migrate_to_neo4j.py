from django.core.management.base import BaseCommand

from app.services import neo4j_memory as neo4j


class Command(BaseCommand):
    help = "One-time migration: export all data from SQLite to Neo4j with ID mapping"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sessionMap = {}
        self.agentMap = {}
        self.memoryMap = {}
        self.planMap = {}
        self.subMap = {}

    def handle(self, *args, **options):
        self.stdout.write("Starting SQLite -> Neo4j migration (with ID mapping)...")

        neo4j.init_neo4j_constraints()
        self.stdout.write("  Neo4j constraints initialized.")

        self._migrate_users()
        self._migrate_agents()
        self._migrate_sessions()
        self._migrate_messages()
        self._migrate_memories()
        self._migrate_memory_bullets()
        self._migrate_documents()
        self._migrate_skills()
        self._migrate_notifications()
        self._migrate_audit_logs()
        self._migrate_request_logs()
        self._migrate_session_members()
        self._migrate_session_participants()
        self._migrate_billing()

        self.stdout.write(self.style.SUCCESS("Migration complete."))

    def _migrate_users(self):
        from app.users.models import UserProfile
        profiles = UserProfile.objects.select_related("user").all()
        count = 0
        for p in profiles:
            neo4j.create_or_update_django_user(
                user_id=str(p.pk),
                username=p.user.username,
                email=p.user.email,
                password_hash=p.user.password,
                display_name=p.display_name or "",
                is_active=p.user.is_active,
                is_staff=p.user.is_staff,
                is_superuser=p.user.is_superuser,
                first_name=p.user.first_name,
                last_name=p.user.last_name,
                uuid=str(p.uuid),
            )
            count += 1
        self.stdout.write(f"  Users: {count}")

    def _migrate_agents(self):
        from app.chat.models.agent import Agent
        count = 0
        for a in Agent.objects.all():
            result = neo4j.create_agent(
                user_id=str(a.user_id),
                name=a.name,
                description=a.description or "",
                system_prompt=a.system_prompt or "",
                temperature=float(a.temperature),
                max_tokens=int(a.max_tokens),
                configuration=a.configuration or {},
            )
            if result.get("id"):
                self.agentMap[a.pk] = result["id"]
            count += 1
        self.stdout.write(f"  Agents: {count} (mapped {len(self.agentMap)} IDs)")

    def _migrate_sessions(self):
        from app.chat.models.session import Session
        count = 0
        for s in Session.objects.all():
            result = neo4j.create_session(
                user_id=str(s.user_id),
                title=s.title or "",
            )
            neoId = result.get("id", "")
            if neoId:
                self.sessionMap[s.pk] = neoId
                if s.access_key:
                    neo4j.update_session(neoId, access_key=s.access_key)
                if s.description:
                    neo4j.update_session(neoId, description=s.description)
            count += 1
        self.stdout.write(f"  Sessions: {count} (mapped {len(self.sessionMap)} IDs)")

    def _migrate_messages(self):
        from app.chat.models.message import Message
        count = 0
        skipped = 0
        for m in Message.objects.select_related("session", "sender_agent").order_by("created_at"):
            neoSessionId = self.sessionMap.get(m.session_id)
            if not neoSessionId:
                skipped += 1
                continue
            neoAgentId = self.agentMap.get(m.sender_agent_id) if m.sender_agent_id else None
            neo4j.create_message(
                session_id=neoSessionId,
                content=m.content,
                created_by=str(m.session.user_id),
                role=str(m.role),
                sender_agent_id=neoAgentId,
                is_ai=(m.role == 3),
            )
            count += 1
        self.stdout.write(f"  Messages: {count} (skipped {skipped})")

    def _migrate_memories(self):
        from app.chat.models.memory import Memory
        count = 0
        for mem in Memory.objects.all():
            result = neo4j.get_or_create_memory(str(mem.user_id))
            neoId = result.get("id", "")
            if neoId:
                self.memoryMap[mem.pk] = neoId
                neo4j.update_memory_fields(
                    neoId,
                    access_clock=mem.access_clock,
                    planner_state=mem.planner_state or {},
                )
            count += 1
        self.stdout.write(f"  Memories: {count} (mapped {len(self.memoryMap)} IDs)")

    def _migrate_memory_bullets(self):
        from app.chat.models.memory_bullet import MemoryBullet
        count = 0
        skipped = 0
        for b in MemoryBullet.objects.all():
            neoMemoryId = self.memoryMap.get(b.memory_id)
            if not neoMemoryId:
                skipped += 1
                continue
            neo4j.create_bullet(
                memory_id=neoMemoryId,
                learner_id=b.learner_id or "",
                content=b.content,
                tags=b.tags or [],
                memory_type=b.memory_type,
                topic=b.topic or "",
                strength=b.strength,
                ttl_days=b.ttl_days,
                concept=b.concept,
                bullet_key=b.bullet_key or "",
                context_scope_id=b.context_scope_id or "",
                content_hash=b.content_hash or "",
                semantic_strength=float(b.semantic_strength or 0),
                episodic_strength=float(b.episodic_strength or 0),
                procedural_strength=float(b.procedural_strength or 0),
                semantic_access_index=b.semantic_access_index,
                episodic_access_index=b.episodic_access_index,
                procedural_access_index=b.procedural_access_index,
                is_skill=b.is_skill,
                skill_enabled=b.skill_enabled,
                skill_group=b.skill_group or "",
                embedding_json=b.embedding_json or "",
            )
            count += 1
        self.stdout.write(f"  MemoryBullets: {count} (skipped {skipped})")

    def _migrate_documents(self):
        from app.chat.models.document import Document
        count = 0
        for d in Document.objects.all():
            neoAgentId = self.agentMap.get(d.agent_id) if d.agent_id else None
            neo4j.create_document(
                user_id=str(d.user_id),
                filename=d.filename,
                raw_text=d.raw_text or "",
                description=d.description or "",
                parsed_fields=d.parsed_fields or {},
                file_size=d.file_size or "",
                ttl_days=d.ttl_days or 7,
                agent_id=neoAgentId,
            )
            count += 1
        self.stdout.write(f"  Documents: {count}")

    def _migrate_skills(self):
        from app.chat.models.skill import Skill
        count = 0
        for sk in Skill.objects.all():
            neo4j.create_skill(
                user_id=str(sk.user_id),
                name=sk.name,
                slug=sk.slug,
                description=sk.description or "",
                content=sk.content or "",
                category=sk.category or "",
                is_enabled=sk.is_enabled,
                source=sk.source,
                source_bullet_ids=sk.source_bullet_ids or [],
            )
            count += 1
        self.stdout.write(f"  Skills: {count}")

    def _migrate_notifications(self):
        from app.chat.models.notification import Notification
        count = 0
        for n in Notification.objects.all():
            neo4j.create_notification(
                user_id=str(n.user_id),
                title=n.title,
                message=n.message or "",
                notification_type=n.notification_type,
                related_url=n.related_url or "",
            )
            count += 1
        self.stdout.write(f"  Notifications: {count}")

    def _migrate_audit_logs(self):
        from app.chat.models.audit_log import AuditLog
        count = 0
        for al in AuditLog.objects.all():
            neoAgentId = self.agentMap.get(al.agent_id) if al.agent_id else None
            neo4j.create_audit_log(
                user_id=str(al.user_id),
                event_type=al.event_type,
                description=al.description or "",
                agent_id=neoAgentId,
                metadata=al.metadata or {},
            )
            count += 1
        self.stdout.write(f"  AuditLogs: {count}")

    def _migrate_request_logs(self):
        from app.chat.models.request_log import RequestLog
        count = 0
        for rl in RequestLog.objects.all():
            neoSessionId = self.sessionMap.get(rl.session_id) if rl.session_id else None
            neo4j.create_request_log(
                user_id=str(rl.user_id),
                session_id=neoSessionId,
                request_type=rl.request_type,
                model_name=rl.model_name,
                pipeline=rl.pipeline,
                status=rl.status,
                latency_ms=rl.latency_ms,
                prompt_tokens=rl.prompt_tokens,
                completion_tokens=rl.completion_tokens,
                total_tokens=rl.total_tokens,
                estimated_cost_usd=float(rl.estimated_cost_usd),
                error_type=rl.error_type or "",
                metadata=rl.metadata or {},
            )
            count += 1
        self.stdout.write(f"  RequestLogs: {count}")

    def _migrate_session_members(self):
        from app.chat.models.session_member import SessionMember
        count = 0
        skipped = 0
        for sm in SessionMember.objects.all():
            neoSessionId = self.sessionMap.get(sm.session_id)
            if not neoSessionId:
                skipped += 1
                continue
            neo4j.add_member_to_session(
                session_id=neoSessionId,
                user_id=str(sm.user_id),
                role=sm.role,
            )
            count += 1
        self.stdout.write(f"  SessionMembers: {count} (skipped {skipped})")

    def _migrate_session_participants(self):
        from app.chat.models.session_participant import SessionParticipant
        count = 0
        skipped = 0
        for sp in SessionParticipant.objects.all():
            neoSessionId = self.sessionMap.get(sp.session_id)
            neoAgentId = self.agentMap.get(sp.agent_id)
            if not neoSessionId or not neoAgentId:
                skipped += 1
                continue
            neo4j.add_agent_to_session(
                session_id=neoSessionId,
                agent_id=neoAgentId,
            )
            count += 1
        self.stdout.write(f"  SessionParticipants: {count} (skipped {skipped})")

    def _migrate_billing(self):
        from app.billing.models.plan import Plan
        from app.billing.models.subscription import Subscription
        from app.billing.models.payment import Payment
        planCount = 0
        for p in Plan.objects.all():
            result = neo4j.create_plan(
                name=p.name,
                code=p.code,
                description=p.description or "",
                interval=p.interval,
                price_cents=p.price_cents,
                currency=p.currency,
                is_active=p.is_active,
            )
            if result.get("id"):
                self.planMap[p.pk] = result["id"]
            planCount += 1
        subCount = 0
        for sub in Subscription.objects.all():
            neoPlanId = self.planMap.get(sub.plan_id)
            result = neo4j.create_subscription(
                user_id=str(sub.user_id),
                plan_id=neoPlanId or str(sub.plan_id),
                status=sub.status,
                auto_renew=sub.auto_renew,
                period_start=str(sub.current_period_start),
                period_end=str(sub.current_period_end),
            )
            if result.get("id"):
                self.subMap[sub.pk] = result["id"]
            subCount += 1
        payCount = 0
        for pay in Payment.objects.all():
            neoSubId = self.subMap.get(pay.subscription_id) if pay.subscription_id else None
            neoPlanId = self.planMap.get(pay.plan_id) if pay.plan_id else None
            neo4j.create_payment(
                user_id=str(pay.user_id),
                subscription_id=neoSubId,
                plan_id=neoPlanId,
                amount_cents=pay.amount_cents,
                currency=pay.currency,
                status=pay.status,
            )
            payCount += 1
        self.stdout.write(f"  Plans: {planCount}, Subscriptions: {subCount}, Payments: {payCount}")
