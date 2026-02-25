import argparse
import os
import sys
import django
from unittest.mock import patch
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "memoria.settings.development")
django.setup()

from django.contrib.auth.models import User as AuthUser
from django.http import Http404
from django.utils import timezone

from app.chat.models import Session, Message, Memory, MemoryBullet
from app.chat.models.message import Role
from app.chat.models.memory_bullet import MemoryType
from app.chat.service import (
    create_home_session_for_user,
    create_user_message_with_agent_reply,
    get_activity_chart_png,
    get_analytics_dashboard_context,
    get_api_analytics_summary_payload,
    get_api_memory_bullets_payload,
    get_api_messages_payload,
    get_api_sessions_payload,
    get_home_context_for_user,
    get_memory_list_data,
    get_memory_strength_chart_png,
    get_memory_summary,
    get_memory_type_chart_png,
    get_session_for_user,
    get_sidebar_sessions_for_user,
)
from app.chat.holiday_service import (
    HolidayAPIUnavailableError,
    InvalidHolidayCountryCodeError,
    get_daily_activity_with_holidays_payload,
)
from app.users.services import (
    create_user_with_profile,
    get_or_create_profile_for_user,
    validate_registration,
)
from unit_test.mock_data import cleanup_all_test_data, create_all_test_data


def assert_test(condition, name):
    if condition:
        print(f"  SUCCESS: {name}")
        return 0
    print(f"  FAILED: {name}")
    return 1


def test_user_services(data):
    print("\n" + "=" * 60)
    print("TEST GROUP A: User Service Functions")
    print("=" * 60)
    failures = 0

    print("\n  --- validate_registration ---")
    result = validate_registration("brand_new_user", "brand_new_user@example.com", "pass123", "pass123")
    failures += assert_test(result is None, "Valid registration returns None")

    result = validate_registration("", "missing_username@example.com", "pass123", "pass123")
    failures += assert_test(result is not None and "username" in result, "Empty username returns error")

    result = validate_registration("maria_garcia", "maria_new@example.com", "pass123", "pass123")
    failures += assert_test(result is not None and "username" in result, "Existing username returns error")

    result = validate_registration("newuser", "newuser@example.com", "pass1", "pass2")
    failures += assert_test(result is not None and "password2" in result, "Mismatched passwords returns error")

    result = validate_registration("newuser", "newuser@example.com", "", "")
    failures += assert_test(result is not None and "password1" in result, "Empty password returns error")

    print("\n  --- create_user_with_profile ---")
    new_user = create_user_with_profile("test_create_tmp", "test_create_tmp@example.com", "pass123")
    profile_exists = hasattr(new_user, "profile") and new_user.profile is not None
    failures += assert_test(
        new_user is not None and profile_exists,
        "create_user_with_profile creates AuthUser and Profile",
    )
    AuthUser.objects.filter(username="test_create_tmp").delete()

    print("\n  --- get_or_create_profile_for_user ---")
    maria_auth = data["auth_users"][0]
    profile1 = get_or_create_profile_for_user(maria_auth)
    profile2 = get_or_create_profile_for_user(maria_auth)
    failures += assert_test(profile1.id == profile2.id, "get_or_create_profile is idempotent")

    return failures


def test_session_services(data):
    print("\n" + "=" * 60)
    print("TEST GROUP B: Session Service Functions")
    print("=" * 60)
    failures = 0

    maria_auth = data["auth_users"][0]
    james_auth = data["auth_users"][1]
    empty_auth = data["auth_users"][5]

    print("\n  --- get_sidebar_sessions_for_user ---")
    sidebar = get_sidebar_sessions_for_user(maria_auth)
    failures += assert_test(sidebar.count() >= 4, "Maria has at least 4 sidebar sessions")

    sidebar_james = get_sidebar_sessions_for_user(james_auth)
    maria_ids = set(sidebar.values_list("id", flat=True))
    james_ids = set(sidebar_james.values_list("id", flat=True))
    failures += assert_test(len(maria_ids & james_ids) == 0, "Sidebar sessions are user-isolated")

    print("\n  --- get_home_context_for_user ---")
    ctx = get_home_context_for_user(maria_auth)
    failures += assert_test(
        "username" in ctx and "sessions" in ctx and "memories" in ctx,
        "Home context has correct keys",
    )

    print("\n  --- create_home_session_for_user ---")
    new_session = create_home_session_for_user(maria_auth, "Test home session content")
    failures += assert_test(new_session is not None, "Valid content creates session")
    if new_session:
        failures += assert_test(new_session.title == "Test home session content", "Session title matches content")
        msg_count = Message.objects.filter(session=new_session).count()
        failures += assert_test(msg_count == 2, "Opening exchange creates 2 messages")

    empty_result = create_home_session_for_user(maria_auth, "")
    failures += assert_test(empty_result is None, "Empty content returns None")

    ws_result = create_home_session_for_user(maria_auth, "   ")
    failures += assert_test(ws_result is None, "Whitespace-only content returns None")

    print("\n  --- get_session_for_user ---")
    valid_session = data["sessions"][0]
    fetched = get_session_for_user(maria_auth, valid_session.id)
    failures += assert_test(fetched.id == valid_session.id, "Valid session ID returns correct session")

    try:
        get_session_for_user(maria_auth, 999999)
        failures += assert_test(False, "Invalid session ID raises Http404")
    except Http404:
        failures += assert_test(True, "Invalid session ID raises Http404")

    james_session = data["sessions"][4]
    try:
        get_session_for_user(maria_auth, james_session.id)
        failures += assert_test(False, "Other user's session raises Http404")
    except Http404:
        failures += assert_test(True, "Other user's session raises Http404")

    fetched_with = get_session_for_user(maria_auth, valid_session.id, with_messages=True)
    failures += assert_test(
        hasattr(fetched_with, "_prefetched_objects_cache"),
        "with_messages=True uses prefetch",
    )

    print("\n  --- create_user_message_with_agent_reply ---")
    test_session = data["sessions"][0]
    before_count = Message.objects.filter(session=test_session).count()
    before_time = timezone.now()
    result = create_user_message_with_agent_reply(test_session, "Hello test message")
    after_count = Message.objects.filter(session=test_session).count()
    failures += assert_test(result is True, "Valid message returns True")
    failures += assert_test(after_count == before_count + 2, "Creates 2 new messages (USER + ASSISTANT)")

    test_session.refresh_from_db()
    failures += assert_test(test_session.updated_at >= before_time, "Session updated_at is refreshed")

    failures += assert_test(
        create_user_message_with_agent_reply(test_session, "") is False,
        "Empty content returns False",
    )
    failures += assert_test(
        create_user_message_with_agent_reply(test_session, "   ") is False,
        "Whitespace-only content returns False",
    )

    return failures


def test_memory_services(data):
    print("\n" + "=" * 60)
    print("TEST GROUP C: Memory Service Functions")
    print("=" * 60)
    failures = 0

    maria_auth = data["auth_users"][0]
    empty_auth = data["auth_users"][5]

    print("\n  --- get_memory_list_data ---")
    result = get_memory_list_data(maria_auth)
    expected_keys = {"queryset", "active_memory_type", "search_query", "sort_label", "active_sort", "memory_type_choices"}
    failures += assert_test(set(result.keys()) == expected_keys, "Returns correct keys")

    filtered = get_memory_list_data(maria_auth, search_query="formal")
    qs = list(filtered["queryset"])
    failures += assert_test(
        all("formal" in b.content.lower() for b in qs),
        "Search query filters by content",
    )

    typed = get_memory_list_data(maria_auth, memory_type="1")
    qs = list(typed["queryset"])
    failures += assert_test(
        all(b.memory_type == MemoryType.SEMANTIC for b in qs),
        "memory_type filter returns correct type",
    )

    sorted_strength = get_memory_list_data(maria_auth, sort_key="strength")
    failures += assert_test(sorted_strength["sort_label"] == "Strength", "Strength sort has correct label")
    failures += assert_test(sorted_strength["active_sort"] == "strength", "Strength sort key is active")

    sorted_affect = get_memory_list_data(maria_auth, sort_key="affect")
    failures += assert_test(sorted_affect["sort_label"] == "Affect", "Affect sort has correct label")

    invalid_sort = get_memory_list_data(maria_auth, sort_key="nonexistent")
    failures += assert_test(invalid_sort["active_sort"] == "created", "Invalid sort falls back to created")

    empty_result = get_memory_list_data(empty_auth)
    failures += assert_test(empty_result["queryset"].count() == 0, "Empty user returns empty queryset")

    print("\n  --- get_memory_summary ---")
    summary = get_memory_summary(maria_auth)
    failures += assert_test(summary["total_count"] == 7, "Maria has 7 memory bullets")
    failures += assert_test(summary["avg_strength"] is not None, "avg_strength is not None")

    empty_summary = get_memory_summary(empty_auth)
    failures += assert_test(empty_summary["total_count"] == 0, "Empty user total_count is 0")
    failures += assert_test(empty_summary["avg_strength"] is None, "Empty user avg_strength is None")

    return failures


def test_analytics_services(data):
    print("\n" + "=" * 60)
    print("TEST GROUP D: Analytics Service Functions")
    print("=" * 60)
    failures = 0

    maria_auth = data["auth_users"][0]
    empty_auth = data["auth_users"][5]

    print("\n  --- get_analytics_dashboard_context ---")
    ctx = get_analytics_dashboard_context(maria_auth)
    expected_keys = {"total_memories", "total_sessions", "total_messages", "avg_strength", "type_summary"}
    failures += assert_test(set(ctx.keys()) == expected_keys, "Returns correct keys")
    failures += assert_test(ctx["total_memories"] >= 7, "Maria has at least 7 memories")

    empty_ctx = get_analytics_dashboard_context(empty_auth)
    failures += assert_test(empty_ctx["total_memories"] == 0, "Empty user has 0 memories")
    failures += assert_test(empty_ctx["total_sessions"] == 0, "Empty user has 0 sessions")

    if ctx["type_summary"]:
        labels = [item["label"] for item in ctx["type_summary"]]
        valid_labels = {"Semantic", "Episodic", "Procedural"}
        failures += assert_test(
            all(label in valid_labels for label in labels),
            "type_summary has valid labels",
        )

    return failures


def test_chart_generation(data):
    print("\n" + "=" * 60)
    print("TEST GROUP E: Chart Generation Functions")
    print("=" * 60)
    failures = 0

    maria_auth = data["auth_users"][0]
    empty_auth = data["auth_users"][5]

    png_header = b"\x89PNG"

    print("\n  --- Chart PNG output ---")
    type_chart = get_memory_type_chart_png(maria_auth)
    failures += assert_test(type_chart[:4] == png_header, "Memory type chart returns valid PNG")

    strength_chart = get_memory_strength_chart_png(maria_auth)
    failures += assert_test(strength_chart[:4] == png_header, "Memory strength chart returns valid PNG")

    activity_chart = get_activity_chart_png(maria_auth)
    failures += assert_test(activity_chart[:4] == png_header, "Activity chart returns valid PNG")

    empty_chart = get_memory_type_chart_png(empty_auth)
    failures += assert_test(empty_chart[:4] == png_header, "Empty user chart still returns valid PNG")

    return failures


def test_api_payloads(data):
    print("\n" + "=" * 60)
    print("TEST GROUP F: API Payload Functions")
    print("=" * 60)
    failures = 0

    maria_auth = data["auth_users"][0]
    empty_auth = data["auth_users"][5]

    print("\n  --- get_api_memory_bullets_payload ---")
    payload = get_api_memory_bullets_payload(maria_auth)
    failures += assert_test("count" in payload and "results" in payload, "Memory payload has count and results")
    failures += assert_test(payload["count"] >= 7, "Maria has at least 7 bullet results")

    if payload["results"]:
        item = payload["results"][0]
        required_fields = {"id", "content", "memory_type", "topic", "strength", "helpful_count", "harmful_count", "created_at", "last_accessed"}
        failures += assert_test(required_fields.issubset(set(item.keys())), "Result items have required fields")

    q_payload = get_api_memory_bullets_payload(maria_auth, q="formal")
    failures += assert_test(
        all("formal" in r["content"].lower() for r in q_payload["results"]),
        "q filter works on API payload",
    )

    type_payload = get_api_memory_bullets_payload(maria_auth, memory_type="1")
    failures += assert_test(
        all(r["memory_type"] == "Semantic" for r in type_payload["results"]),
        "type filter returns Semantic only",
    )

    topic_payload = get_api_memory_bullets_payload(maria_auth, topic="Communication")
    failures += assert_test(
        all("communication" in r["topic"].lower() for r in topic_payload["results"]),
        "topic filter works on API payload",
    )

    strength_payload = get_api_memory_bullets_payload(maria_auth, strength_min="50")
    failures += assert_test(
        all(r["strength"] >= 50 for r in strength_payload["results"]),
        "strength_min filter returns strength >= 50",
    )

    limit_payload = get_api_memory_bullets_payload(maria_auth, limit=2)
    failures += assert_test(limit_payload["count"] <= 2, "Limit restricts result count")

    combined = get_api_memory_bullets_payload(maria_auth, q="formal", memory_type="1")
    failures += assert_test(
        all("formal" in r["content"].lower() and r["memory_type"] == "Semantic" for r in combined["results"]),
        "Combined filters work together",
    )

    empty_payload = get_api_memory_bullets_payload(empty_auth)
    failures += assert_test(empty_payload["count"] == 0, "Empty user returns count=0")

    print("\n  --- get_api_analytics_summary_payload ---")
    analytics = get_api_analytics_summary_payload(maria_auth)
    expected_keys = {"total_memories", "total_sessions", "type_distribution", "avg_strength", "total_helpful", "total_harmful"}
    failures += assert_test(expected_keys.issubset(set(analytics.keys())), "Analytics payload has correct keys")

    print("\n  --- get_api_sessions_payload ---")
    sessions_payload = get_api_sessions_payload(maria_auth)
    failures += assert_test("count" in sessions_payload and "results" in sessions_payload, "Sessions payload has count and results")
    failures += assert_test(sessions_payload["count"] >= 4, "Maria has at least 4 session results")

    q_sessions = get_api_sessions_payload(maria_auth, q="Planning")
    failures += assert_test(
        all("planning" in r["title"].lower() for r in q_sessions["results"]),
        "Sessions q filter works",
    )

    limit_sessions = get_api_sessions_payload(maria_auth, limit=1)
    failures += assert_test(limit_sessions["count"] <= 1, "Sessions limit restricts results")

    print("\n  --- get_api_messages_payload ---")
    valid_session = data["sessions"][0]
    msg_payload = get_api_messages_payload(maria_auth, valid_session.id)
    failures += assert_test(
        "session_id" in msg_payload and "count" in msg_payload and "messages" in msg_payload,
        "Messages payload has correct structure",
    )

    role_payload = get_api_messages_payload(maria_auth, valid_session.id, role_filter="2")
    failures += assert_test(
        all(m["role"] == "User" for m in role_payload["messages"]),
        "Role filter returns only USER messages",
    )

    try:
        get_api_messages_payload(maria_auth, 999999)
        failures += assert_test(False, "Invalid session in messages raises Http404")
    except Http404:
        failures += assert_test(True, "Invalid session in messages raises Http404")

    return failures


def test_model_methods(data):
    print("\n" + "=" * 60)
    print("TEST GROUP G: Model Method Tests")
    print("=" * 60)
    failures = 0

    maria_profile = data["profiles"][0]

    print("\n  --- Session.create_with_opening_exchange ---")
    session = Session.create_with_opening_exchange(maria_profile, "Hello world")
    failures += assert_test(session is not None, "Valid content returns Session")
    if session:
        failures += assert_test(session.title == "Hello world", "Title matches content")
        msgs = Message.objects.filter(session=session)
        failures += assert_test(msgs.count() == 2, "Creates USER + ASSISTANT messages")

    custom = Session.create_with_opening_exchange(maria_profile, "Hi there", assistant_reply="Custom reply")
    if custom:
        assistant_msg = Message.objects.filter(session=custom, role=Role.ASSISTANT).first()
        failures += assert_test(
            assistant_msg is not None and assistant_msg.content == "Custom reply",
            "Custom assistant_reply is used",
        )

    long_content = "X" * 300
    long_session = Session.create_with_opening_exchange(maria_profile, long_content)
    if long_session:
        failures += assert_test(len(long_session.title) <= 200, "Title is truncated to max 200 chars")

    empty_session = Session.create_with_opening_exchange(maria_profile, "")
    failures += assert_test(empty_session is None, "Empty content returns None")

    print("\n  --- get_absolute_url ---")
    valid_session = data["sessions"][0]
    url = valid_session.get_absolute_url()
    failures += assert_test(url.startswith("/chat/c/"), "Session URL starts with /chat/c/")

    valid_memory = data["memories"][0]
    url = valid_memory.get_absolute_url()
    failures += assert_test(url.startswith("/chat/m/"), "Memory URL starts with /chat/m/")

    return failures


def test_edge_cases(data):
    print("\n" + "=" * 60)
    print("TEST GROUP H: Edge Case Tests")
    print("=" * 60)
    failures = 0

    empty_auth = data["auth_users"][5]

    print("\n  --- Empty user service results ---")
    sidebar = get_sidebar_sessions_for_user(empty_auth)
    failures += assert_test(sidebar.count() == 0, "Empty user has 0 sidebar sessions")

    ctx = get_home_context_for_user(empty_auth)
    failures += assert_test(ctx["sessions"].count() == 0, "Empty user home has 0 sessions")

    summary = get_memory_summary(empty_auth)
    failures += assert_test(summary["total_count"] == 0, "Empty user memory summary total is 0")

    analytics = get_analytics_dashboard_context(empty_auth)
    failures += assert_test(analytics["total_memories"] == 0, "Empty user analytics has 0 memories")

    print("\n  --- Filter edge cases ---")
    from app.chat.service import _apply_memory_bullet_filters
    qs = MemoryBullet.objects.all()

    filtered = _apply_memory_bullet_filters(qs, strength_min="")
    failures += assert_test(filtered.count() == qs.count(), "Empty strength_min applies no filter")

    filtered = _apply_memory_bullet_filters(qs, strength_min="abc")
    failures += assert_test(filtered.count() == qs.count(), "Non-numeric strength_min applies no filter")

    filtered = _apply_memory_bullet_filters(qs, memory_type="abc")
    failures += assert_test(filtered.count() == qs.count(), "Non-numeric memory_type applies no filter")

    filtered = _apply_memory_bullet_filters(qs, q="", memory_type="", topic="", strength_min="")
    failures += assert_test(filtered.count() == qs.count(), "All empty params apply no filters")

    return failures


def test_holiday_merge_service(data):
    print("\n" + "=" * 60)
    print("TEST GROUP I: Holiday Merge Service")
    print("=" * 60)
    failures = 0

    class MockResponse:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError("HTTP error")

        def json(self):
            return self._payload

    def mock_get_success(url, params=None, timeout=5):
        if "AvailableCountries" in url:
            return MockResponse([
                {"countryCode": "US", "name": "United States"},
                {"countryCode": "CA", "name": "Canada"},
            ])
        if "PublicHolidays" in url and "/US" in url:
            return MockResponse([
                {"date": "2026-01-01", "name": "New Year's Day", "localName": "New Year's Day"},
            ])
        return MockResponse([])

    with patch("app.chat.holiday_service.requests.get", side_effect=mock_get_success):
        payload = get_daily_activity_with_holidays_payload(country_code="US")
        failures += assert_test("results" in payload and "analytics" in payload, "Holiday payload has results and analytics")

    with patch("app.chat.holiday_service.requests.get", side_effect=mock_get_success):
        try:
            get_daily_activity_with_holidays_payload(country_code="ZZ")
            failures += assert_test(False, "Invalid country code should raise error")
        except InvalidHolidayCountryCodeError:
            failures += assert_test(True, "Invalid country code raises InvalidHolidayCountryCodeError")

    with patch("app.chat.holiday_service.requests.get", side_effect=requests.RequestException("network down")):
        try:
            get_daily_activity_with_holidays_payload(country_code="US")
            failures += assert_test(False, "Unavailable API should raise error")
        except HolidayAPIUnavailableError:
            failures += assert_test(True, "Unavailable API raises HolidayAPIUnavailableError")

    return failures


def main():
    parser = argparse.ArgumentParser(description="MEMORIA Feature Tests")
    parser.add_argument("--test-users", action="store_true", help="Run user service tests")
    parser.add_argument("--test-sessions", action="store_true", help="Run session service tests")
    parser.add_argument("--test-memory", action="store_true", help="Run memory service tests")
    parser.add_argument("--test-analytics", action="store_true", help="Run analytics service tests")
    parser.add_argument("--test-charts", action="store_true", help="Run chart generation tests")
    parser.add_argument("--test-api", action="store_true", help="Run API payload tests")
    parser.add_argument("--test-models", action="store_true", help="Run model method tests")
    parser.add_argument("--test-edge", action="store_true", help="Run edge case tests")
    parser.add_argument("--test-holidays", action="store_true", help="Run holiday merge service tests")
    args = parser.parse_args()

    print("=" * 60)
    print("MEMORIA FEATURE TEST SUITE")
    print("=" * 60)

    print("\nSetting up test data...")
    cleanup_all_test_data()
    data = create_all_test_data()

    has_specific = any([
        args.test_users, args.test_sessions, args.test_memory,
        args.test_analytics, args.test_charts, args.test_api,
        args.test_models, args.test_edge, args.test_holidays,
    ])

    failures = 0

    if not has_specific or args.test_users:
        failures += test_user_services(data)
    if not has_specific or args.test_sessions:
        failures += test_session_services(data)
    if not has_specific or args.test_memory:
        failures += test_memory_services(data)
    if not has_specific or args.test_analytics:
        failures += test_analytics_services(data)
    if not has_specific or args.test_charts:
        failures += test_chart_generation(data)
    if not has_specific or args.test_api:
        failures += test_api_payloads(data)
    if not has_specific or args.test_models:
        failures += test_model_methods(data)
    if not has_specific or args.test_edge:
        failures += test_edge_cases(data)
    if not has_specific or args.test_holidays:
        failures += test_holiday_merge_service(data)

    print("\n" + "=" * 60)
    if failures > 0:
        print(f"RESULT: {failures} test(s) FAILED")
    else:
        print("RESULT: All tests PASSED")
    print("=" * 60)

    sys.exit(failures)


if __name__ == "__main__":
    main()
