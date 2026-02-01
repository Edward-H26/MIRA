import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mira.settings.development")
django.setup()

from django.contrib.auth.models import User as AuthUser
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.utils import timezone
from datetime import date, timedelta

from app.users.models import User
from app.chat.models import Session, Message, Memory, MemoryBullet
from app.chat.models.message import Role
from app.chat.models.memory_bullet import MemoryType
from app.billing.models import Plan, Subscription, Payment
from app.billing.models.plan import Interval
from app.billing.models.subscription import Status as SubscriptionStatus
from app.billing.models.payment import Status as PaymentStatus


def create_test_data():
    """Create 5 users, each with 1 Memory containing 2 MemoryBullets."""

    print("=" * 60)
    print("STEP 1: Creating 5 Users with Profiles")
    print("=" * 60)

    users_data = [
        {"username": "maria_garcia", "email": "maria@example.com", "first_name": "Maria", "last_name": "Garcia"},
        {"username": "james_chen", "email": "james@example.com", "first_name": "James", "last_name": "Chen"},
        {"username": "sarah_johnson", "email": "sarah@example.com", "first_name": "Sarah", "last_name": "Johnson"},
        {"username": "alex_kumar", "email": "alex@example.com", "first_name": "Alex", "last_name": "Kumar"},
        {"username": "emma_wilson", "email": "emma@example.com", "first_name": "Emma", "last_name": "Wilson"},
    ]

    profiles = []
    for data in users_data:
        auth_user = AuthUser.objects.create_user(
            username=data["username"],
            email=data["email"],
            password="testpass123",
            first_name=data["first_name"],
            last_name=data["last_name"]
        )
        profile = User.objects.create(user=auth_user)
        profiles.append(profile)
        print(f"  Created user: {data['username']} (Profile ID: {profile.id})")

    maria, james, sarah, alex, emma = profiles

    print("\n" + "=" * 60)
    print("STEP 2: Creating Plans")
    print("=" * 60)

    plans_data = [
        {"name": "Free Tier", "code": "free", "description": "Basic access with limited features", "interval": Interval.MONTHLY, "price_cents": 0},
        {"name": "Pro Monthly", "code": "pro", "description": "Full access to all features", "interval": Interval.MONTHLY, "price_cents": 999},
        {"name": "Pro Yearly", "code": "pro", "description": "Full access, billed annually", "interval": Interval.YEARLY, "price_cents": 9999},
    ]

    plans = []
    for data in plans_data:
        plan = Plan.objects.create(**data)
        plans.append(plan)
        print(f"  Created plan: {data['name']} (code={data['code']}, interval={data['interval']})")

    free_plan, pro_monthly, pro_yearly = plans

    print("\n" + "=" * 60)
    print("STEP 3: Creating Memory Records (1 per user)")
    print("=" * 60)

    memories = []
    for i, profile in enumerate(profiles):
        memory = Memory.objects.create(user=profile, access_clock=i * 5 + 1)
        memories.append(memory)
        print(f"  Created Memory ID {memory.id} for user {profile.user.username}")

    print("\n" + "=" * 60)
    print("STEP 4: Creating PRIMARY MODEL - MemoryBullets (2 per user = 10 total)")
    print("=" * 60)
    print("  Demonstrating FK Relationship: Multiple MemoryBullets -> Single Memory -> User")
    print()

    bullets_data = [
        {"memory": memories[0], "content": "Prefers formal communication style", "tags": ["style"], "memory_type": MemoryType.SEMANTIC, "topic": "Communication", "ttl_days": 365, "strength": 8},
        {"memory": memories[0], "content": "Works as a software engineer", "tags": ["profession"], "memory_type": MemoryType.SEMANTIC, "topic": "Career", "ttl_days": 365, "strength": 9},
        {"memory": memories[1], "content": "Enjoys Python programming", "tags": ["skills"], "memory_type": MemoryType.PROCEDURAL, "topic": "Technical Skills", "ttl_days": 180, "strength": 10},
        {"memory": memories[1], "content": "Prefers step-by-step explanations", "tags": ["learning"], "memory_type": MemoryType.PROCEDURAL, "topic": "Learning Style", "ttl_days": 180, "strength": 7},
        {"memory": memories[2], "content": "Had productive meeting on project timeline", "tags": ["work"], "memory_type": MemoryType.EPISODIC, "topic": "Work Events", "ttl_days": 90, "strength": 5},
        {"memory": memories[2], "content": "Enjoys hiking on weekends", "tags": ["hobbies"], "memory_type": MemoryType.SEMANTIC, "topic": "Personal Interests", "ttl_days": 365, "strength": 6},
        {"memory": memories[3], "content": "Studies machine learning", "tags": ["education"], "memory_type": MemoryType.SEMANTIC, "topic": "Education", "ttl_days": 365, "strength": 8},
        {"memory": memories[3], "content": "Uses VS Code as primary editor", "tags": ["tools"], "memory_type": MemoryType.PROCEDURAL, "topic": "Development Tools", "ttl_days": 180, "strength": 7},
        {"memory": memories[4], "content": "Leads a product team of 5 people", "tags": ["work"], "memory_type": MemoryType.SEMANTIC, "topic": "Role", "ttl_days": 365, "strength": 9},
        {"memory": memories[4], "content": "Prefers visual diagrams for architecture", "tags": ["style"], "memory_type": MemoryType.PROCEDURAL, "topic": "Preferences", "ttl_days": 180, "strength": 8},
    ]

    for i, data in enumerate(bullets_data):
        bullet = MemoryBullet.objects.create(**data)
        user = data["memory"].user.user.username
        print(f"  [{i+1}/10] MemoryBullet ID {bullet.id} -> Memory ID {data['memory'].id} -> User: {user}")

    print(f"\n  Total MemoryBullets created: {MemoryBullet.objects.count()}")

    print("\n" + "=" * 60)
    print("STEP 5: Creating Sessions and Messages (Additional FK Relationships)")
    print("=" * 60)

    session1 = Session.objects.create(user=maria, title="Project Planning Discussion")
    session2 = Session.objects.create(user=james, title="Code Review Help")

    Message.objects.create(session=session1, role=Role.USER, content="Can you help me plan my new project?")
    Message.objects.create(session=session1, role=Role.ASSISTANT, content="Of course! What kind of project are you working on?")
    Message.objects.create(session=session2, role=Role.USER, content="I need help reviewing this Python function.")
    Message.objects.create(session=session2, role=Role.ASSISTANT, content="Sure, please share the code.")

    print(f"  Created Session '{session1.title}' with 2 messages for {maria.user.username}")
    print(f"  Created Session '{session2.title}' with 2 messages for {james.user.username}")
    print(f"  FK Chain: Message -> Session -> User (profile) -> auth.User")

    print("\n" + "=" * 60)
    print("STEP 6: Creating Subscriptions and Payments")
    print("=" * 60)

    today = date.today()

    sub1 = Subscription.objects.create(
        user=maria,
        plan=pro_monthly,
        status=SubscriptionStatus.ACTIVE,
        auto_renew=True,
        current_period_start=today,
        current_period_end=today + timedelta(days=30)
    )
    print(f"  Subscription: {maria.user.username} -> {pro_monthly.name}")

    sub2 = Subscription.objects.create(
        user=james,
        plan=free_plan,
        status=SubscriptionStatus.ACTIVE,
        auto_renew=False,
        current_period_start=today,
        current_period_end=today + timedelta(days=30)
    )
    print(f"  Subscription: {james.user.username} -> {free_plan.name}")

    payment1 = Payment.objects.create(
        user=maria,
        subscription=sub1,
        plan=pro_monthly,
        amount_cents=999,
        status=PaymentStatus.SUCCEEDED,
        paid_at=timezone.now()
    )
    print(f"  Payment: {maria.user.username} paid $9.99 for {pro_monthly.name}")

    return {
        "profiles": profiles,
        "plans": plans,
        "memories": memories,
        "subscriptions": [sub1, sub2],
        "payments": [payment1],
    }


def test_fk_relationships(data):
    """Demonstrate FK relationships: multiple records linked to single parent."""

    print("\n" + "=" * 60)
    print("TEST: Foreign Key Relationships")
    print("=" * 60)

    for memory in data["memories"]:
        bullets = MemoryBullet.objects.filter(memory=memory)
        user = memory.user.user.username
        print(f"  User '{user}' -> Memory ID {memory.id} -> {bullets.count()} MemoryBullets")
        for bullet in bullets:
            print(f"      - '{bullet.content[:40]}...'")

    print("\n  SUCCESS: Each Memory has multiple MemoryBullets demonstrating FK relationships")


def test_uniqueness_constraints(data):
    """Test uniqueness constraints on Plan and Subscription."""

    print("\n" + "=" * 60)
    print("TEST: Uniqueness Constraint Validation")
    print("=" * 60)

    print("\n  Test 1: Attempting to create duplicate Plan (code='pro', interval=MONTHLY)...")
    try:
        duplicate_plan = Plan.objects.create(
            name="Another Pro Monthly",
            code="pro",
            description="Duplicate attempt",
            interval=Interval.MONTHLY,
            price_cents=1999
        )
        print("  FAILED: Duplicate plan was allowed!")
    except IntegrityError:
        print("  SUCCESS: IntegrityError raised - Plan uniqueness constraint works!")

    print("\n  Test 2: Attempting duplicate Subscription (maria + pro_monthly)...")
    maria = data["profiles"][0]
    pro_monthly = data["plans"][1]

    try:
        duplicate_sub = Subscription.objects.create(
            user=maria,
            plan=pro_monthly,
            status=SubscriptionStatus.ACTIVE,
            current_period_start=date.today(),
            current_period_end=date.today() + timedelta(days=30)
        )
        print("  FAILED: Duplicate subscription was allowed!")
    except IntegrityError:
        print("  SUCCESS: IntegrityError raised - Subscription uniqueness constraint works!")


def test_on_delete_behaviors(data):
    """Test CASCADE, PROTECT, and SET_NULL on_delete behaviors."""

    print("\n" + "=" * 60)
    print("TEST: on_delete Behavior Validation")
    print("=" * 60)

    print("\n  Test 1: on_delete=PROTECT (attempting to delete Plan with Subscriptions)...")
    pro_monthly = data["plans"][1]

    try:
        pro_monthly.delete()
        print("  FAILED: Plan deletion was allowed!")
    except ProtectedError:
        print("  SUCCESS: ProtectedError raised - Cannot delete Plan with active Subscriptions!")

    print("\n  Test 2: on_delete=SET_NULL (deleting Subscription, checking Payment)...")
    sub1 = data["subscriptions"][0]
    payment = data["payments"][0]

    print(f"    Before: Payment.subscription_id = {payment.subscription_id}")
    sub1.delete()
    payment.refresh_from_db()
    print(f"    After:  Payment.subscription_id = {payment.subscription_id}")

    if payment.subscription_id is None:
        print("  SUCCESS: SET_NULL worked - Payment.subscription is now NULL!")
    else:
        print("  FAILED: SET_NULL did not work!")

    print("\n  Test 3: on_delete=CASCADE (deleting User, checking related records)...")
    emma = data["profiles"][4]
    emma_id = emma.id
    emma_memory_count = Memory.objects.filter(user=emma).count()
    emma_bullet_count = MemoryBullet.objects.filter(memory__user=emma).count()

    print(f"    Before: Emma has {emma_memory_count} Memory, {emma_bullet_count} MemoryBullets")
    emma.delete()

    remaining_memories = Memory.objects.filter(user_id=emma_id).count()
    remaining_bullets = MemoryBullet.objects.filter(memory__user_id=emma_id).count()

    print(f"    After:  {remaining_memories} Memory, {remaining_bullets} MemoryBullets remaining")

    if remaining_memories == 0 and remaining_bullets == 0:
        print("  SUCCESS: CASCADE worked - All related records deleted!")
    else:
        print("  FAILED: CASCADE did not remove all related records!")


def print_summary():
    """Print final database state summary."""

    print("\n" + "=" * 60)
    print("FINAL DATABASE STATE SUMMARY")
    print("=" * 60)

    print(f"  AuthUser records:     {AuthUser.objects.filter(username__in=['maria_garcia', 'james_chen', 'sarah_johnson', 'alex_kumar', 'emma_wilson']).count()}")
    print(f"  User profiles:        {User.objects.count()}")
    print(f"  Memory records:       {Memory.objects.count()}")
    print(f"  MemoryBullet records: {MemoryBullet.objects.count()}")
    print(f"  Session records:      {Session.objects.count()}")
    print(f"  Message records:      {Message.objects.count()}")
    print(f"  Plan records:         {Plan.objects.count()}")
    print(f"  Subscription records: {Subscription.objects.count()}")
    print(f"  Payment records:      {Payment.objects.count()}")


if __name__ == "__main__":
    print("\n" + "#" * 60)
    print("# MIRA Test Data Insertion Script")
    print("# INFO 490 - Database Validation")
    print("#" * 60 + "\n")

    data = create_test_data()
    test_fk_relationships(data)
    test_uniqueness_constraints(data)
    test_on_delete_behaviors(data)
    print_summary()

    print("\n" + "#" * 60)
    print("# All tests completed!")
    print("#" * 60 + "\n")
