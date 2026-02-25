import os
import sys
import django


def _pop_settings_arg(argv):
    for index, arg in enumerate(argv):
        if arg.startswith("--settings="):
            value = arg.split("=", 1)[1].strip()
            del argv[index]
            return value
        if arg == "--settings" and index + 1 < len(argv):
            value = argv[index + 1].strip()
            del argv[index:index + 2]
            return value
    return None


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
settings_module = _pop_settings_arg(sys.argv) or os.environ.get("DJANGO_SETTINGS_MODULE") or "memoria.settings.dev"
os.environ["DJANGO_SETTINGS_MODULE"] = settings_module
django.setup()

from datetime import date, timedelta
from django.contrib.auth.models import User as AuthUser
from django.utils import timezone

from app.users.models import UserProfile
from app.chat.models import Session, Message, Memory, MemoryBullet
from app.chat.models.message import Role
from app.chat.models.memory_bullet import MemoryType
from app.billing.models import Plan, Subscription, Payment
from app.billing.models.plan import Interval
from app.billing.models.subscription import Status as SubscriptionStatus
from app.billing.models.payment import Status as PaymentStatus


def _backdate_session(session, days_ago):
    """Backdate a session's created_at and updated_at (auto_now fields ignore direct assignment)."""
    ts = timezone.now() - timedelta(days=days_ago)
    Session.objects.filter(pk=session.pk).update(created_at=ts, updated_at=ts)


def _backdate_message(message, days_ago, minute_offset=0):
    """Backdate a message created_at to align with the target day."""
    base_ts = timezone.now() - timedelta(days=days_ago, hours=12)
    ts = base_ts + timedelta(minutes=minute_offset)
    Message.objects.filter(pk=message.pk).update(created_at=ts)


def _create_backdated_conversation(
    user_profile,
    title,
    days_ago,
    user_prompt,
    assistant_reply,
    user_followup=None,
):
    """
    Create one session with 2-3 messages (always includes assistant reply),
    then backdate both session and messages to the same day.
    """
    session = Session.objects.create(user=user_profile, title=title)
    _backdate_session(session, days_ago=days_ago)

    created_messages = []
    m1 = Message.objects.create(session=session, role=Role.USER, content=user_prompt)
    _backdate_message(m1, days_ago=days_ago, minute_offset=0)
    created_messages.append(m1)

    m2 = Message.objects.create(session=session, role=Role.ASSISTANT, content=assistant_reply)
    _backdate_message(m2, days_ago=days_ago, minute_offset=2)
    created_messages.append(m2)

    if user_followup:
        m3 = Message.objects.create(session=session, role=Role.USER, content=user_followup)
        _backdate_message(m3, days_ago=days_ago, minute_offset=4)
        created_messages.append(m3)

    return session, created_messages


TEST_USERNAMES = [
    "maria_garcia", "james_chen", "sarah_johnson", "alex_kumar",
    "emma_wilson", "test_edge_empty", "test_edge_maxlen", "test_edge_special",
]

TEST_PLAN_CODES = ["free", "pro", "enterprise", "legacy"]

USERS_DATA = [
    {"username": "maria_garcia", "email": "maria@example.com", "first_name": "Maria", "last_name": "Garcia"},
    {"username": "james_chen", "email": "james@example.com", "first_name": "James", "last_name": "Chen"},
    {"username": "sarah_johnson", "email": "sarah@example.com", "first_name": "Sarah", "last_name": "Johnson"},
    {"username": "alex_kumar", "email": "alex@example.com", "first_name": "Alex", "last_name": "Kumar"},
    {"username": "emma_wilson", "email": "emma@example.com", "first_name": "Emma", "last_name": "Wilson"},
    {"username": "test_edge_empty", "email": "empty@example.com", "first_name": "", "last_name": ""},
    {"username": "test_edge_maxlen", "email": "maxlen@example.com", "first_name": "A" * 30, "last_name": "B" * 30},
    {"username": "test_edge_special", "email": "special@example.com", "first_name": "O'Brien", "last_name": "von-Strasse"},
]

PLANS_DATA = [
    {"name": "Free Tier", "code": "free", "description": "Basic access with limited features", "interval": Interval.MONTHLY, "price_cents": 0},
    {"name": "Pro Monthly", "code": "pro", "description": "Full access to all features", "interval": Interval.MONTHLY, "price_cents": 999},
    {"name": "Pro Yearly", "code": "pro", "description": "Full access, billed annually", "interval": Interval.YEARLY, "price_cents": 9999},
    {"name": "Enterprise Monthly", "code": "enterprise", "description": "Enterprise-grade features with priority support", "interval": Interval.MONTHLY, "price_cents": 4999},
    {"name": "Deprecated Plan", "code": "legacy", "description": "No longer available for purchase", "interval": Interval.MONTHLY, "price_cents": 499, "is_active": False},
]


def cleanup_all_test_data():
    existing_users = AuthUser.objects.filter(username__in=TEST_USERNAMES)
    user_count = existing_users.count()

    if user_count > 0:
        existing_users.delete()
        print(f"  Cleaned up {user_count} test user(s) and cascaded records")

    existing_plans = Plan.objects.filter(code__in=TEST_PLAN_CODES)
    plan_count = existing_plans.count()

    if plan_count > 0:
        existing_plans.delete()
        print(f"  Cleaned up {plan_count} test plan(s)")

    # Clean admin user's seeded chat data (keep the admin account itself)
    try:
        admin_auth = AuthUser.objects.get(username="tester")
        admin_profile = UserProfile.objects.filter(user=admin_auth).first()
        if admin_profile:
            s_count = Session.objects.filter(user=admin_profile).count()
            m_count = Memory.objects.filter(user=admin_profile).count()
            Session.objects.filter(user=admin_profile).delete()
            Memory.objects.filter(user=admin_profile).delete()
            if s_count or m_count:
                print(f"  Cleaned admin 'tester' chat data ({s_count} sessions, {m_count} memories)")
    except AuthUser.DoesNotExist:
        pass


def create_all_test_data():
    print("=" * 60)
    print("CREATING COMPREHENSIVE TEST DATA")
    print("=" * 60)

    print("\n  Step 1: Creating 8 Users with Profiles")
    profiles = []
    for data in USERS_DATA:
        auth_user = AuthUser.objects.create_user(
            username=data["username"],
            email=data["email"],
            password="testpass123",
            first_name=data["first_name"],
            last_name=data["last_name"],
        )
        profile = UserProfile.objects.create(user=auth_user)
        profiles.append(profile)
        print(f"    Created: {data['username']}")

    maria, james, sarah, alex, emma, edge_empty, edge_maxlen, edge_special = profiles

    print("\n  Step 2: Creating 5 Plans")
    plans = []
    for data in PLANS_DATA:
        plan = Plan.objects.create(**data)
        plans.append(plan)
        print(f"    Created: {data['name']} (code={data['code']}, interval={data['interval']})")

    free_plan, pro_monthly, pro_yearly, enterprise, legacy_plan = plans

    print("\n  Step 3: Creating 7 Memory Records")
    memory_users = [maria, james, sarah, alex, emma, edge_maxlen, edge_special]
    memories = []
    for i, profile in enumerate(memory_users):
        memory = Memory.objects.create(user=profile, access_clock=i * 5 + 1)
        memories.append(memory)
        print(f"    Memory ID {memory.id} for {profile.user.username}")

    print("\n  Step 4: Creating 26 MemoryBullets")
    bullets_data = [
        {"memory": memories[0], "content": "Prefers formal communication style", "tags": ["style"], "memory_type": MemoryType.SEMANTIC, "topic": "Communication", "ttl_days": 365, "strength": 8, "helpful_count": 5, "harmful_count": 0},
        {"memory": memories[0], "content": "Works as a software engineer", "tags": ["profession"], "memory_type": MemoryType.SEMANTIC, "topic": "Career", "ttl_days": 365, "strength": 9, "helpful_count": 3, "harmful_count": 1, "concept": "software engineering"},
        {"memory": memories[0], "content": "Expert in distributed systems architecture and microservices deployment patterns", "tags": ["skills", "architecture", "distributed"], "memory_type": MemoryType.PROCEDURAL, "topic": "Technical Skills", "ttl_days": 180, "strength": 75, "helpful_count": 10, "harmful_count": 2, "concept": "distributed systems"},
        {"memory": memories[0], "content": "Had productive meeting on project timeline", "tags": ["work"], "memory_type": MemoryType.EPISODIC, "topic": "Work Events", "ttl_days": 90, "strength": 100, "helpful_count": 0, "harmful_count": 0},
        {"memory": memories[0], "content": "Completed marathon in under 4 hours last spring", "tags": ["fitness", "achievement"], "memory_type": MemoryType.EPISODIC, "topic": "Personal", "ttl_days": 365, "strength": 50, "helpful_count": 1, "harmful_count": 0},
        {"memory": memories[0], "content": "Prefers dark mode in all development tools", "tags": ["preferences"], "memory_type": MemoryType.SEMANTIC, "topic": "Preferences", "ttl_days": 9999, "strength": 6, "helpful_count": 2, "harmful_count": 3},
        {"memory": memories[0], "content": "Uses Docker and Kubernetes for container orchestration", "tags": ["tools", "devops"], "memory_type": MemoryType.PROCEDURAL, "topic": "DevOps", "ttl_days": 180, "strength": 25, "helpful_count": 4, "harmful_count": 0, "concept": "containerization"},

        {"memory": memories[1], "content": "Enjoys Python programming", "tags": ["skills"], "memory_type": MemoryType.PROCEDURAL, "topic": "Technical Skills", "ttl_days": 180, "strength": 10, "helpful_count": 1, "harmful_count": 0},
        {"memory": memories[1], "content": "Prefers step-by-step explanations", "tags": ["learning"], "memory_type": MemoryType.PROCEDURAL, "topic": "Learning Style", "ttl_days": 180, "strength": 7},
        {"memory": memories[1], "content": "Studies machine learning", "tags": ["education"], "memory_type": MemoryType.SEMANTIC, "topic": "Education", "ttl_days": 365, "strength": 50, "helpful_count": 2, "harmful_count": 1, "concept": "machine learning"},
        {"memory": memories[1], "content": "Uses VS Code as primary editor", "tags": ["tools"], "memory_type": MemoryType.PROCEDURAL, "topic": "Development Tools", "ttl_days": 180, "strength": 25, "helpful_count": 1, "harmful_count": 0, "concept": "VS Code"},
        {"memory": memories[1], "content": "a", "tags": [], "memory_type": MemoryType.SEMANTIC, "topic": "Test", "ttl_days": 1, "strength": 0},

        {"memory": memories[2], "content": "Enjoys hiking on weekends", "tags": ["hobbies"], "memory_type": MemoryType.EPISODIC, "topic": "Personal Interests", "ttl_days": 365, "strength": 5},
        {"memory": memories[2], "content": "Attended team retrospective meeting on Friday where we discussed Q3 goals and planned the roadmap for the next quarter with key stakeholders from three different departments plus the executive sponsor and the product lead from the remote office", "tags": ["work", "meetings", "planning"], "memory_type": MemoryType.EPISODIC, "topic": "Work Events", "ttl_days": 90, "strength": 6, "concept": "team meetings"},
        {"memory": memories[2], "content": "Remembered childhood vacation to beach", "tags": ["personal"], "memory_type": MemoryType.EPISODIC, "topic": "Personal Memories", "ttl_days": 365, "strength": 9, "helpful_count": 1, "harmful_count": 0},
        {"memory": memories[2], "content": "First day at new job orientation completed", "tags": ["work", "milestone"], "memory_type": MemoryType.EPISODIC, "topic": "Career", "ttl_days": 180, "strength": 8},
        {"memory": memories[2], "content": "Debugging session solved critical production issue", "tags": ["work"], "memory_type": MemoryType.EPISODIC, "topic": "Technical", "ttl_days": 90, "strength": 0, "helpful_count": 0, "harmful_count": 5},

        {"memory": memories[3], "content": "Studies machine learning", "tags": ["education"], "memory_type": MemoryType.SEMANTIC, "topic": "Education", "ttl_days": 365, "strength": 7},
        {"memory": memories[3], "content": "Uses VS Code as primary editor", "tags": ["tools"], "memory_type": MemoryType.PROCEDURAL, "topic": "Development Tools", "ttl_days": 180, "strength": 8},

        {"memory": memories[4], "content": "Leads a product team of 5 people", "tags": ["work"], "memory_type": MemoryType.SEMANTIC, "topic": "Role", "ttl_days": 365, "strength": 9, "helpful_count": 3, "harmful_count": 0, "concept": "leadership"},
        {"memory": memories[4], "content": "Prefers visual diagrams for architecture", "tags": ["style"], "memory_type": MemoryType.PROCEDURAL, "topic": "Preferences", "ttl_days": 180, "strength": 8, "helpful_count": 1, "harmful_count": 0},
        {"memory": memories[4], "content": "Conducted quarterly performance reviews", "tags": ["management"], "memory_type": MemoryType.EPISODIC, "topic": "Management", "ttl_days": 90, "strength": 50, "helpful_count": 2, "harmful_count": 1, "concept": "performance reviews"},

        {"memory": memories[5], "content": "X" * 500, "tags": ["tag1", "tag2", "tag3"], "memory_type": MemoryType.SEMANTIC, "topic": "A" * 200, "ttl_days": 9999, "strength": 100, "helpful_count": 99, "harmful_count": 99, "concept": "C" * 200},
        {"memory": memories[5], "content": "Normal content for maxlen user", "tags": ["normal"], "memory_type": MemoryType.PROCEDURAL, "topic": "Normal Topic", "ttl_days": 0, "strength": 5},

        {"memory": memories[6], "content": "Prefers cafe-style discussions with naive approaches and HTML tags", "tags": ["special", "cafe"], "memory_type": MemoryType.SEMANTIC, "topic": "Special Topic", "ttl_days": 365, "strength": 7},
        {"memory": memories[6], "content": "Resume highlights include multi-paradigm programming", "tags": [], "memory_type": MemoryType.PROCEDURAL, "topic": "Career", "ttl_days": 180, "strength": 5},
    ]

    bullets = []
    for data in bullets_data:
        bullet = MemoryBullet.objects.create(**data)
        bullets.append(bullet)
    print(f"    Created {len(bullets)} MemoryBullets across {len(memories)} memories")

    print("\n  Step 5: Creating daily Sessions and Messages (2-3 per conversation)")
    sessions = []
    messages = []

    # Keep the first five deterministic for existing tests that index into data["sessions"].
    seeded = [
        (maria, "Project Planning Discussion", 29, "Can you help me plan my new project?", "Of course. What are your goals?", "A web app for task management."),
        (maria, "Architecture Review", 28, "What backend pattern should I use?", "A service-layer approach works well here.", None),
        (maria, "Quick Question", 27, "What is binary search time complexity?", "It is O(log n).", None),
        (maria, "", 26, "Can we keep this untitled chat?", "Yes, untitled chats are supported.", None),
        (james, "Code Review Help", 25, "Can you review this Python function?", "Sure, share the code and expected behavior.", "I also want naming feedback."),
    ]
    for profile, title, days_ago, user_prompt, assistant_reply, followup in seeded:
        s, created_msgs = _create_backdated_conversation(
            user_profile=profile,
            title=title,
            days_ago=days_ago,
            user_prompt=user_prompt,
            assistant_reply=assistant_reply,
            user_followup=followup,
        )
        sessions.append(s)
        messages.extend(created_msgs)

    templates = [
        ("Python Debugging", "My script crashes with a TypeError.", "Please share the traceback.", "Here is the traceback snippet."),
        ("Learning Resources", "What resources are best for Django?", "The official docs and tutorial series are a great start.", None),
        ("Career Planning", "I am planning my next career step.", "Let's map your current skills to target roles.", "Can you suggest a 3-month plan?"),
        ("Weekend Plans", "Any good hiking suggestions nearby?", "Try a moderate trail with early morning start.", None),
        ("Team Standup Notes", "Today I worked on API endpoints.", "Great progress. Any blockers?", None),
        ("Feature Prioritization", "How should we prioritize backlog items?", "Use impact vs effort scoring with clear owners.", "Can you draft a simple rubric?"),
        ("Data Modeling", "Should we denormalize this table?", "Only if query hotspots justify it.", None),
        ("Deployment Checklist", "What should I verify before deploy?", "Migrations, env vars, static files, and health checks.", None),
        ("Prompt Refinement", "How can I improve this prompt?", "Make the task, constraints, and output format explicit.", "Can you give an example rewrite?"),
        ("Cafe Discussion and Review", "Content with special characters and symbols", "Noted. I can preserve special formatting safely.", None),
    ]
    active_profiles = [maria, james, sarah, alex, emma, edge_maxlen, edge_special]

    # Build a natural daily pattern for the last 25 days (days_ago: 24 -> 0), at least 1 session/day.
    for days_ago in range(24, -1, -1):
        day_date = (timezone.now() - timedelta(days=days_ago)).date()
        daily_sessions = 1 if day_date.weekday() >= 5 else 2  # weekends lighter
        if day_date.day % 9 == 0:
            daily_sessions += 1  # occasional spikes

        for idx in range(daily_sessions):
            profile = active_profiles[(days_ago + idx) % len(active_profiles)]
            title, user_prompt, assistant_reply, followup = templates[(days_ago * 3 + idx) % len(templates)]

            # Keep edge case coverage for max title length naturally.
            if profile == edge_maxlen and idx == 0 and days_ago % 8 == 0:
                session_title = "A" * 200
            else:
                session_title = title

            # 2-3 messages per conversation, including assistant.
            include_followup = followup if (days_ago + idx) % 3 == 0 else None

            s, created_msgs = _create_backdated_conversation(
                user_profile=profile,
                title=session_title,
                days_ago=days_ago,
                user_prompt=user_prompt,
                assistant_reply=assistant_reply,
                user_followup=include_followup,
            )
            sessions.append(s)
            messages.extend(created_msgs)

    print(f"    Created {len(sessions)} sessions and {len(messages)} messages")

    print("\n  Step 6: Creating 5 Subscriptions")
    today = date.today()

    sub1 = Subscription.objects.create(
        user=maria, plan=pro_monthly, status=SubscriptionStatus.ACTIVE,
        auto_renew=True, current_period_start=today, current_period_end=today + timedelta(days=30),
    )
    sub2 = Subscription.objects.create(
        user=james, plan=free_plan, status=SubscriptionStatus.ACTIVE,
        auto_renew=False, current_period_start=today, current_period_end=today + timedelta(days=30),
    )
    sub3 = Subscription.objects.create(
        user=sarah, plan=pro_yearly, status=SubscriptionStatus.EXPIRED,
        auto_renew=True, current_period_start=today - timedelta(days=365), current_period_end=today - timedelta(days=1),
    )
    sub4 = Subscription.objects.create(
        user=alex, plan=free_plan, status=SubscriptionStatus.INCOMPLETE,
        auto_renew=False, current_period_start=today, current_period_end=today + timedelta(days=30),
    )
    sub5 = Subscription.objects.create(
        user=emma, plan=enterprise, status=SubscriptionStatus.ACTIVE,
        auto_renew=True, current_period_start=today, current_period_end=today + timedelta(days=30),
    )
    subscriptions = [sub1, sub2, sub3, sub4, sub5]
    print(f"    Created {len(subscriptions)} subscriptions (ACTIVE, EXPIRED, INCOMPLETE)")

    print("\n  Step 7: Creating 7 Payments")
    now = timezone.now()

    pay1 = Payment.objects.create(
        user=maria, subscription=sub1, plan=pro_monthly,
        amount_cents=999, status=PaymentStatus.SUCCEEDED, paid_at=now,
    )
    pay2 = Payment.objects.create(
        user=maria, subscription=sub1, plan=pro_monthly,
        amount_cents=999, status=PaymentStatus.SUCCEEDED, paid_at=now - timedelta(days=30),
    )
    pay3 = Payment.objects.create(
        user=sarah, subscription=sub3, plan=pro_yearly,
        amount_cents=9999, status=PaymentStatus.SUCCEEDED, paid_at=now - timedelta(days=90),
    )
    pay4 = Payment.objects.create(
        user=sarah, subscription=sub3, plan=pro_yearly,
        amount_cents=9999, status=PaymentStatus.FAILED,
    )
    pay5 = Payment.objects.create(
        user=emma, subscription=sub5, plan=enterprise,
        amount_cents=4999, status=PaymentStatus.SUCCEEDED, paid_at=now,
    )
    pay6 = Payment.objects.create(
        user=alex, subscription=sub4, plan=free_plan,
        amount_cents=0, status=PaymentStatus.PENDING,
    )
    pay7 = Payment.objects.create(
        user=james, subscription=sub2, plan=free_plan,
        amount_cents=0, status=PaymentStatus.CANCELLED,
    )
    payments = [pay1, pay2, pay3, pay4, pay5, pay6, pay7]
    print(f"    Created {len(payments)} payments (SUCCEEDED, FAILED, PENDING, CANCELLED)")

    print("\n  Step 8: Seeding admin 'tester' account with demo data")
    try:
        admin_auth = AuthUser.objects.get(username="tester")
        admin_profile, _ = UserProfile.objects.get_or_create(user=admin_auth)

        admin_sessions = []
        admin_messages = []
        admin_templates = [
            ("Project Planning Discussion", "Can you help me plan my new project?", "Of course. What type of project is it?", "A web app for task management."),
            ("Architecture Review", "What pattern should I use for backend modules?", "A service layer with clear boundaries is solid.", None),
            ("Python Debugging", "My script fails with a TypeError.", "Please share traceback and sample input.", "Here is a minimal repro."),
            ("Learning Resources", "Best resources for Django?", "Start with official docs and build one mini-project.", None),
            ("Code Review Help", "Can you review this function?", "Sure, share it with expected behavior.", None),
            ("Release Notes Draft", "Help me summarize this sprint.", "Use a structure: shipped, fixed, known issues.", None),
        ]

        # Admin gets natural daily activity for last 14 days.
        for days_ago in range(13, -1, -1):
            day_date = (timezone.now() - timedelta(days=days_ago)).date()
            daily_sessions = 1 if day_date.weekday() >= 5 else 2
            if day_date.day % 10 == 0:
                daily_sessions += 1

            for idx in range(daily_sessions):
                title, user_prompt, assistant_reply, followup = admin_templates[(days_ago + idx) % len(admin_templates)]
                include_followup = followup if (days_ago + idx) % 2 == 0 else None
                s, created_msgs = _create_backdated_conversation(
                    user_profile=admin_profile,
                    title=title,
                    days_ago=days_ago,
                    user_prompt=user_prompt,
                    assistant_reply=assistant_reply,
                    user_followup=include_followup,
                )
                admin_sessions.append(s)
                admin_messages.extend(created_msgs)

        admin_mem = Memory.objects.create(user=admin_profile, access_clock=10)
        admin_bullets = [
            MemoryBullet.objects.create(memory=admin_mem, content="Prefers formal communication style", tags=["style"], memory_type=MemoryType.SEMANTIC, topic="Communication", ttl_days=365, strength=8, helpful_count=5),
            MemoryBullet.objects.create(memory=admin_mem, content="Works as a software engineer", tags=["profession"], memory_type=MemoryType.SEMANTIC, topic="Career", ttl_days=365, strength=9, helpful_count=3, concept="software engineering"),
            MemoryBullet.objects.create(memory=admin_mem, content="Uses Django and Python for backend development", tags=["skills"], memory_type=MemoryType.PROCEDURAL, topic="Technical Skills", ttl_days=180, strength=75, helpful_count=10, concept="Django"),
            MemoryBullet.objects.create(memory=admin_mem, content="Had productive meeting on project timeline", tags=["work"], memory_type=MemoryType.EPISODIC, topic="Work Events", ttl_days=90, strength=50),
            MemoryBullet.objects.create(memory=admin_mem, content="Prefers dark mode in all development tools", tags=["preferences"], memory_type=MemoryType.SEMANTIC, topic="Preferences", ttl_days=9999, strength=6),
        ]

        print(f"    Created {len(admin_sessions)} sessions, {len(admin_messages)} messages, 1 memory, {len(admin_bullets)} bullets for admin 'tester'")
    except AuthUser.DoesNotExist:
        print("    Skipped: no 'tester' admin account found")

    print("\n" + "=" * 60)
    print("TEST DATA CREATION COMPLETE")
    print("=" * 60)

    return {
        "auth_users": [p.user for p in profiles],
        "profiles": profiles,
        "plans": plans,
        "memories": memories,
        "bullets": bullets,
        "sessions": sessions,
        "messages": messages,
        "subscriptions": subscriptions,
        "payments": payments,
    }


if __name__ == "__main__":
    cleanup_all_test_data()
    create_all_test_data()
