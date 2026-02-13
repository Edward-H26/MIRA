import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "memoria.settings.development")
django.setup()

from datetime import date, timedelta
from django.contrib.auth.models import User as AuthUser
from django.utils import timezone

from app.users.models import User
from app.chat.models import Session, Message, Memory, MemoryBullet
from app.chat.models.message import Role
from app.chat.models.memory_bullet import MemoryType
from app.billing.models import Plan, Subscription, Payment
from app.billing.models.plan import Interval
from app.billing.models.subscription import Status as SubscriptionStatus
from app.billing.models.payment import Status as PaymentStatus


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
        profile = User.objects.create(user=auth_user)
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

    print("\n  Step 5: Creating 12 Sessions and 36 Messages")
    sessions = []
    messages = []

    s1 = Session.objects.create(user=maria, title="Project Planning Discussion")
    sessions.append(s1)
    messages.append(Message.objects.create(session=s1, role=Role.USER, content="Can you help me plan my new project?"))
    messages.append(Message.objects.create(session=s1, role=Role.ASSISTANT, content="Of course! What kind of project are you working on?"))
    messages.append(Message.objects.create(session=s1, role=Role.USER, content="A web application for task management."))

    s2 = Session.objects.create(user=maria, title="Architecture Review")
    sessions.append(s2)
    messages.append(Message.objects.create(session=s2, role=Role.SYSTEM, content="Session started with architecture review context."))
    messages.append(Message.objects.create(session=s2, role=Role.USER, content="What patterns should I use for the backend?"))
    messages.append(Message.objects.create(session=s2, role=Role.ASSISTANT, content="I recommend a service layer architecture."))
    messages.append(Message.objects.create(session=s2, role=Role.USER, content="Can you elaborate?"))
    messages.append(Message.objects.create(session=s2, role=Role.ASSISTANT, content="Sure, let me break it down."))

    s3 = Session.objects.create(user=maria, title="Quick Question")
    sessions.append(s3)
    messages.append(Message.objects.create(session=s3, role=Role.USER, content="What is the time complexity of binary search?"))

    s4 = Session.objects.create(user=maria, title="")
    sessions.append(s4)

    s5 = Session.objects.create(user=james, title="Code Review Help")
    sessions.append(s5)
    messages.append(Message.objects.create(session=s5, role=Role.USER, content="I need help reviewing this Python function."))
    messages.append(Message.objects.create(session=s5, role=Role.ASSISTANT, content="Sure, please share the code."))

    s6 = Session.objects.create(user=james, title="Python Debugging")
    sessions.append(s6)
    messages.append(Message.objects.create(session=s6, role=Role.USER, content="My script crashes with a TypeError."))
    messages.append(Message.objects.create(session=s6, role=Role.ASSISTANT, content="Can you share the traceback?"))
    messages.append(Message.objects.create(session=s6, role=Role.USER, content="Here it is..."))
    messages.append(Message.objects.create(session=s6, role=Role.ASSISTANT, content="The issue is a type mismatch on line 42."))

    s7 = Session.objects.create(user=james, title="Learning Resources")
    sessions.append(s7)
    messages.append(Message.objects.create(session=s7, role=Role.SYSTEM, content="Context: Learning path discussion."))
    messages.append(Message.objects.create(session=s7, role=Role.USER, content="What resources do you recommend for Django?"))
    messages.append(Message.objects.create(session=s7, role=Role.ASSISTANT, content="I recommend the official Django documentation."))

    s8 = Session.objects.create(user=sarah, title="Career Planning")
    sessions.append(s8)
    career_messages = [
        (Role.USER, "I'm considering a career change."),
        (Role.ASSISTANT, "What field are you interested in?"),
        (Role.USER, "Data science seems promising."),
        (Role.ASSISTANT, "That's a growing field. What's your current background?"),
        (Role.USER, "I have a CS degree and 3 years of backend development."),
        (Role.ASSISTANT, "You have a strong foundation."),
        (Role.USER, "What skills should I focus on?"),
        (Role.ASSISTANT, "Python, statistics, and machine learning fundamentals."),
        (Role.USER, "Any course recommendations?"),
        (Role.ASSISTANT, "I recommend starting with Andrew Ng's ML course."),
    ]
    for role, content in career_messages:
        messages.append(Message.objects.create(session=s8, role=role, content=content))

    s9 = Session.objects.create(user=sarah, title="Weekend Plans")
    sessions.append(s9)
    messages.append(Message.objects.create(session=s9, role=Role.USER, content="Any suggestions for hiking trails?"))
    messages.append(Message.objects.create(session=s9, role=Role.ASSISTANT, content="I recommend the Pacific Crest Trail section near you."))

    s10 = Session.objects.create(user=emma, title="Team Standup Notes")
    sessions.append(s10)
    messages.append(Message.objects.create(session=s10, role=Role.USER, content="Today I worked on the API endpoints."))
    messages.append(Message.objects.create(session=s10, role=Role.ASSISTANT, content="Great progress! Any blockers?"))

    s11 = Session.objects.create(user=edge_maxlen, title="A" * 200)
    sessions.append(s11)
    messages.append(Message.objects.create(session=s11, role=Role.USER, content="Testing maximum length content."))
    messages.append(Message.objects.create(session=s11, role=Role.ASSISTANT, content="Acknowledged."))

    s12 = Session.objects.create(user=edge_special, title="Cafe Discussion and Review")
    sessions.append(s12)
    messages.append(Message.objects.create(session=s12, role=Role.USER, content="Content with special characters and symbols"))
    messages.append(Message.objects.create(session=s12, role=Role.ASSISTANT, content="Noted the special formatting."))

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
