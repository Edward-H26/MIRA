import argparse
import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "memoria.settings.development")
django.setup()

from django.contrib.auth.models import User as AuthUser
from django.db import IntegrityError, transaction
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

from unit_test.mock_data import (
    TEST_USERNAMES,
    TEST_PLAN_CODES,
    cleanup_all_test_data,
    create_all_test_data,
)


def assert_test(condition, name):
    if condition:
        print(f"  SUCCESS: {name}")
        return 0
    print(f"  FAILED: {name}")
    return 1


def get_test_data():
    profiles = list(User.objects.filter(user__username__in=TEST_USERNAMES).order_by("id"))
    if len(profiles) < 8:
        return None

    plans = list(Plan.objects.filter(code__in=TEST_PLAN_CODES).order_by("id"))
    if len(plans) < 5:
        return None

    memories = list(Memory.objects.filter(user__in=profiles).order_by("id"))
    sessions = list(Session.objects.filter(user__in=profiles).order_by("id"))
    subscriptions = list(Subscription.objects.filter(user__in=profiles).order_by("id"))
    payments = list(Payment.objects.filter(user__in=profiles).order_by("id"))

    return {
        "profiles": profiles,
        "plans": plans,
        "memories": memories,
        "sessions": sessions,
        "subscriptions": subscriptions,
        "payments": payments,
    }


def test_fk_relationships(data):
    print("\n" + "=" * 60)
    print("TEST: Foreign Key Relationships")
    print("=" * 60)
    failures = 0

    print("\n  --- Memory -> MemoryBullet chain ---")
    for memory in data["memories"]:
        bullets = MemoryBullet.objects.filter(memory=memory)
        user = memory.user.user.username
        print(f"  User '{user}' -> Memory ID {memory.id} -> {bullets.count()} MemoryBullets")
        for bullet in bullets:
            print(f"      - '{bullet.content[:40]}...'")

    failures += assert_test(
        all(MemoryBullet.objects.filter(memory=m).count() > 0 for m in data["memories"]),
        "Every Memory has at least 1 MemoryBullet",
    )

    print("\n  --- Session -> Message chain ---")
    sessions_with_msgs = [s for s in data["sessions"] if Message.objects.filter(session=s).exists()]
    for session in sessions_with_msgs[:3]:
        msg_count = Message.objects.filter(session=session).count()
        print(f"  Session '{session.title[:30]}' -> {msg_count} Messages")

    failures += assert_test(len(sessions_with_msgs) >= 8, "At least 8 sessions have messages")

    print("\n  --- Subscription -> Payment chain ---")
    sub_with_payments = data["subscriptions"][0]
    pay_count = Payment.objects.filter(subscription=sub_with_payments).count()
    print(f"  Subscription ID {sub_with_payments.id} -> {pay_count} Payment(s)")
    failures += assert_test(pay_count >= 1, "Subscription has at least 1 payment")

    return failures


def test_uniqueness_constraints(data):
    print("\n" + "=" * 60)
    print("TEST: Uniqueness Constraint Validation")
    print("=" * 60)
    failures = 0

    print("\n  Test 1: Attempting to create duplicate Plan (code='pro', interval=MONTHLY)...")
    try:
        with transaction.atomic():
            Plan.objects.create(
                name="Another Pro Monthly",
                code="pro",
                description="Duplicate attempt",
                interval=Interval.MONTHLY,
                price_cents=1999,
            )
        failures += assert_test(False, "Duplicate plan should be rejected")
    except IntegrityError:
        failures += assert_test(True, "IntegrityError raised for duplicate Plan")

    print("\n  Test 2: Attempting duplicate Subscription (maria + pro_monthly)...")
    maria = data["profiles"][0]
    pro_monthly = data["plans"][1]

    try:
        with transaction.atomic():
            Subscription.objects.create(
                user=maria,
                plan=pro_monthly,
                status=SubscriptionStatus.ACTIVE,
                current_period_start=date.today(),
                current_period_end=date.today() + timedelta(days=30),
            )
        failures += assert_test(False, "Duplicate subscription should be rejected")
    except IntegrityError:
        failures += assert_test(True, "IntegrityError raised for duplicate Subscription")

    return failures


def test_expanded_uniqueness(data):
    print("\n" + "=" * 60)
    print("TEST: Expanded Uniqueness Constraints")
    print("=" * 60)
    failures = 0

    print("\n  Test 1: Attempting duplicate Plan (code='enterprise', interval=MONTHLY)...")
    try:
        with transaction.atomic():
            Plan.objects.create(
                name="Duplicate Enterprise",
                code="enterprise",
                description="Duplicate attempt",
                interval=Interval.MONTHLY,
                price_cents=9999,
            )
        failures += assert_test(False, "Duplicate enterprise plan should be rejected")
    except IntegrityError:
        failures += assert_test(True, "IntegrityError raised for duplicate enterprise Plan")

    print("\n  Test 2: Attempting duplicate Subscription (sarah + pro_yearly)...")
    sarah = data["profiles"][2]
    pro_yearly = data["plans"][2]

    try:
        with transaction.atomic():
            Subscription.objects.create(
                user=sarah,
                plan=pro_yearly,
                status=SubscriptionStatus.ACTIVE,
                current_period_start=date.today(),
                current_period_end=date.today() + timedelta(days=30),
            )
        failures += assert_test(False, "Duplicate sarah subscription should be rejected")
    except IntegrityError:
        failures += assert_test(True, "IntegrityError raised for duplicate sarah Subscription")

    return failures


def test_model_methods(data):
    print("\n" + "=" * 60)
    print("TEST: Model Method Validation")
    print("=" * 60)
    failures = 0

    maria_profile = data["profiles"][0]

    print("\n  --- Session.create_with_opening_exchange ---")
    session = Session.create_with_opening_exchange(maria_profile, "Database test content")
    failures += assert_test(session is not None, "Valid content returns Session")
    if session:
        failures += assert_test(session.title == "Database test content", "Title matches content")
        msg_count = Message.objects.filter(session=session).count()
        failures += assert_test(msg_count == 2, "Creates 2 messages (USER + ASSISTANT)")

    empty = Session.create_with_opening_exchange(maria_profile, "")
    failures += assert_test(empty is None, "Empty content returns None")

    whitespace = Session.create_with_opening_exchange(maria_profile, "   ")
    failures += assert_test(whitespace is None, "Whitespace content returns None")

    print("\n  --- get_absolute_url ---")
    valid_session = data["sessions"][0]
    session_url = valid_session.get_absolute_url()
    failures += assert_test(
        session_url == f"/chat/c/{valid_session.pk}/",
        f"Session URL is /chat/c/{valid_session.pk}/",
    )

    valid_memory = data["memories"][0]
    memory_url = valid_memory.get_absolute_url()
    failures += assert_test(
        memory_url == f"/chat/m/{valid_memory.pk}/",
        f"Memory URL is /chat/m/{valid_memory.pk}/",
    )

    print("\n  --- __str__ methods ---")
    maria_profile = data["profiles"][0]
    failures += assert_test(str(maria_profile) == "maria_garcia", "User profile __str__ returns username")

    valid_session = data["sessions"][0]
    failures += assert_test("Project Planning" in str(valid_session), "Session __str__ contains title")

    return failures


def test_expanded_on_delete(data):
    """Test Payment.plan SET_NULL by deleting a plan with no subscriptions."""
    print("\n" + "=" * 60)
    print("TEST: Expanded on_delete Behaviors")
    print("=" * 60)
    failures = 0

    print("\n  Test 1: Payment.plan SET_NULL (deleting legacy plan)...")
    legacy_plan = data["plans"][4]
    maria_profile = data["profiles"][0]

    tmp_payment = Payment.objects.create(
        user=maria_profile,
        plan=legacy_plan,
        amount_cents=499,
        status=PaymentStatus.SUCCEEDED,
        paid_at=timezone.now(),
    )

    print(f"    Before: Payment.plan_id = {tmp_payment.plan_id}")
    legacy_plan.delete()
    tmp_payment.refresh_from_db()
    print(f"    After:  Payment.plan_id = {tmp_payment.plan_id}")

    failures += assert_test(tmp_payment.plan_id is None, "SET_NULL worked for Payment.plan")

    return failures


def test_on_delete_behaviors(data):
    print("\n" + "=" * 60)
    print("TEST: on_delete Behavior Validation")
    print("=" * 60)
    failures = 0

    print("\n  Test 1: on_delete=PROTECT (attempting to delete Plan with Subscriptions)...")
    pro_monthly = data["plans"][1]

    try:
        pro_monthly.delete()
        failures += assert_test(False, "Plan deletion should be blocked")
    except ProtectedError:
        failures += assert_test(True, "ProtectedError raised for Plan with active Subscriptions")

    print("\n  Test 2: on_delete=SET_NULL (deleting Subscription, checking Payment)...")
    sub1 = data["subscriptions"][0]
    payment = data["payments"][0]

    print(f"    Before: Payment.subscription_id = {payment.subscription_id}")
    sub1.delete()
    payment.refresh_from_db()
    print(f"    After:  Payment.subscription_id = {payment.subscription_id}")

    failures += assert_test(payment.subscription_id is None, "SET_NULL worked for Payment.subscription")

    print("\n  Test 3: on_delete=CASCADE (deleting auth.User, checking full cascade)...")
    emma = data["profiles"][4]
    emma_auth_user = emma.user
    emma_profile_id = emma.id

    emma_memory_count = Memory.objects.filter(user=emma).count()
    emma_bullet_count = MemoryBullet.objects.filter(memory__user=emma).count()
    emma_session_count = Session.objects.filter(user=emma).count()
    emma_message_count = Message.objects.filter(session__user=emma).count()

    print(f"    Before: Emma has Profile, {emma_memory_count} Memory, {emma_bullet_count} Bullets, {emma_session_count} Sessions, {emma_message_count} Messages")

    emma_auth_user.delete()

    remaining_profiles = User.objects.filter(id=emma_profile_id).count()
    remaining_memories = Memory.objects.filter(user_id=emma_profile_id).count()
    remaining_bullets = MemoryBullet.objects.filter(memory__user_id=emma_profile_id).count()
    remaining_sessions = Session.objects.filter(user_id=emma_profile_id).count()
    remaining_messages = Message.objects.filter(session__user_id=emma_profile_id).count()

    print(f"    After:  {remaining_profiles} Profile, {remaining_memories} Memory, {remaining_bullets} Bullets, {remaining_sessions} Sessions, {remaining_messages} Messages")

    all_gone = (remaining_profiles == 0 and remaining_memories == 0 and
                remaining_bullets == 0 and remaining_sessions == 0 and remaining_messages == 0)
    failures += assert_test(all_gone, "CASCADE removed all related records through full chain")

    return failures


def print_summary():
    print("\n" + "=" * 60)
    print("FINAL DATABASE STATE SUMMARY")
    print("=" * 60)

    print(f"  AuthUser records:     {AuthUser.objects.filter(username__in=TEST_USERNAMES).count()}")
    print(f"  User profiles:        {User.objects.filter(user__username__in=TEST_USERNAMES).count()}")
    print(f"  Memory records:       {Memory.objects.count()}")
    print(f"  MemoryBullet records: {MemoryBullet.objects.count()}")
    print(f"  Session records:      {Session.objects.count()}")
    print(f"  Message records:      {Message.objects.count()}")
    print(f"  Plan records:         {Plan.objects.filter(code__in=TEST_PLAN_CODES).count()}")
    print(f"  Subscription records: {Subscription.objects.count()}")
    print(f"  Payment records:      {Payment.objects.count()}")


def main():
    parser = argparse.ArgumentParser(description="MEMORIA Database Unit Tests")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    parser.add_argument("--setup", action="store_true", help="Cleanup and create test data")
    parser.add_argument("--cleanup", action="store_true", help="Remove test data")
    parser.add_argument("--test-fk", action="store_true", help="Run FK relationships test")
    parser.add_argument("--test-unique", action="store_true", help="Run uniqueness constraints test")
    parser.add_argument("--test-delete", action="store_true", help="Run on_delete behaviors test")
    parser.add_argument("--test-methods", action="store_true", help="Run model method tests")
    parser.add_argument("--summary", action="store_true", help="Print database summary")
    args = parser.parse_args()

    if args.cleanup:
        cleanup_all_test_data()
        return

    if args.setup:
        cleanup_all_test_data()
        create_all_test_data()
        return

    if args.summary:
        print_summary()
        return

    has_specific = args.test_fk or args.test_unique or args.test_delete or args.test_methods

    if has_specific:
        data = get_test_data()
        if data is None:
            print("ERROR: Test data not found. Run with --setup first.")
            sys.exit(1)

        failures = 0
        if args.test_fk:
            failures += test_fk_relationships(data)
        if args.test_unique:
            failures += test_uniqueness_constraints(data)
            failures += test_expanded_uniqueness(data)
        if args.test_methods:
            failures += test_model_methods(data)
        if args.test_delete:
            failures += test_expanded_on_delete(data)
            failures += test_on_delete_behaviors(data)
    else:
        cleanup_all_test_data()
        data = create_all_test_data()
        failures = 0
        failures += test_fk_relationships(data)
        failures += test_uniqueness_constraints(data)
        failures += test_expanded_uniqueness(data)
        failures += test_model_methods(data)
        failures += test_expanded_on_delete(data)
        failures += test_on_delete_behaviors(data)
        print_summary()

    print("\n" + "=" * 60)
    if failures > 0:
        print(f"RESULT: {failures} test(s) FAILED")
    else:
        print("RESULT: All tests PASSED")
    print("=" * 60)

    sys.exit(failures)


if __name__ == "__main__":
    main()
