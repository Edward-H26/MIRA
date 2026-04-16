"""Cross-user data isolation regression tests.

Covers the two confirmed leaks that caused "everyone sees the same history":
  1. Context processor _user_id() must never fall back to request.user.pk when
     the UserProfile lookup fails. Falling back conflates two separate id
     namespaces and causes cached sidebars to swap across users.
  2. Pusher channel auth must reject subscriptions to sessions the requester
     does not own or belong to, and to /private-user-<uid>/ channels where
     uid does not match the requester's profile.pk.
"""
import os
import sys
import uuid
from unittest.mock import MagicMock, PropertyMock, patch

import django
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "memoria.settings.dev")
django.setup()

from django.contrib.auth.models import User as AuthUser
from django.core.cache import cache
from django.test import Client

from app.services import neo4j_memory as neo4j
from app.users.models import UserProfile
from app.users.services import get_or_create_profile_for_user


@pytest.fixture
def two_isolated_users(db):
    """Create two users with distinct profiles and one Neo4j-backed session
    each. Cleans Neo4j state for those users at teardown so reruns are clean."""
    usernameA = f"iso_a_{uuid.uuid4().hex[:8]}"
    usernameB = f"iso_b_{uuid.uuid4().hex[:8]}"
    userA = AuthUser.objects.create_user(username=usernameA, password="pw", email=f"{usernameA}@t.local")
    userB = AuthUser.objects.create_user(username=usernameB, password="pw", email=f"{usernameB}@t.local")
    profileA = get_or_create_profile_for_user(userA)
    profileB = get_or_create_profile_for_user(userB)

    sessionA = neo4j.create_session(str(profileA.pk), "A private chat")
    sessionB = neo4j.create_session(str(profileB.pk), "B private chat")

    cache.clear()

    yield {
        "userA": userA, "profileA": profileA, "sessionA": sessionA,
        "userB": userB, "profileB": profileB, "sessionB": sessionB,
    }

    try:
        neo4j.delete_session(str(sessionA["id"]))
        neo4j.delete_session(str(sessionB["id"]))
        neo4j.delete_user_cascade(str(profileA.pk))
        neo4j.delete_user_cascade(str(profileB.pk))
    except Exception:
        pass
    cache.clear()


def _make_request(user):
    req = MagicMock()
    req.user = user
    req.user.is_authenticated = True
    return req


def test_user_id_fallback_fails_closed(two_isolated_users):
    """When profile resolution raises, _user_id returns "" and callers return
    their empty default. Before the fix, it fell back to request.user.pk and
    could accidentally return a colliding user's cached data."""
    from app.chat.context_processors import user_sessions

    userA = two_isolated_users["userA"]
    req = _make_request(userA)

    with patch("app.users.services.get_or_create_profile_for_user", side_effect=Exception("simulated profile miss")):
        result = user_sessions(req)

    assert result == {"sessions": []}, f"expected empty fallback, got {result}"


def test_sidebar_sessions_are_per_user(two_isolated_users):
    """Happy path: each user sees only their own sessions in the sidebar."""
    from app.chat.context_processors import user_sessions

    reqA = _make_request(two_isolated_users["userA"])
    reqB = _make_request(two_isolated_users["userB"])

    sessionsA = user_sessions(reqA)["sessions"]
    sessionsB = user_sessions(reqB)["sessions"]

    idsA = {str(s.get("id", "")) for s in sessionsA}
    idsB = {str(s.get("id", "")) for s in sessionsB}
    assert idsA & idsB == set(), f"A and B sidebars overlapped: {idsA & idsB}"
    assert str(two_isolated_users["sessionA"]["id"]) in idsA
    assert str(two_isolated_users["sessionB"]["id"]) in idsB
    assert str(two_isolated_users["sessionB"]["id"]) not in idsA
    assert str(two_isolated_users["sessionA"]["id"]) not in idsB


def test_user_can_access_session_matrix(two_isolated_users):
    """The Neo4j ACL helper must say yes for owners, no for outsiders."""
    d = two_isolated_users
    assert neo4j.user_can_access_session(str(d["profileA"].pk), str(d["sessionA"]["id"])) is True
    assert neo4j.user_can_access_session(str(d["profileB"].pk), str(d["sessionB"]["id"])) is True
    assert neo4j.user_can_access_session(str(d["profileA"].pk), str(d["sessionB"]["id"])) is False
    assert neo4j.user_can_access_session(str(d["profileB"].pk), str(d["sessionA"]["id"])) is False
    assert neo4j.user_can_access_session("", str(d["sessionA"]["id"])) is False
    assert neo4j.user_can_access_session(str(d["profileA"].pk), "") is False


def test_pusher_auth_rejects_foreign_session(two_isolated_users):
    """User A must not be able to authenticate the Pusher channel for B's
    session. Pre-fix, any authenticated user could obtain a token for any
    private-group-<id> channel."""
    d = two_isolated_users
    client = Client()
    client.force_login(d["userA"])

    response = client.post(
        "/chat/api/pusher/auth/",
        data={
            "socket_id": "1234.5678",
            "channel_name": f"private-group-{d['sessionB']['id']}",
        },
    )
    assert response.status_code == 403, f"expected 403, got {response.status_code}"


def test_pusher_auth_allows_owner(two_isolated_users):
    """User B subscribing to their own session channel: ACL passes. Auth
    itself may still return None if Pusher creds are unset in dev — that is
    OK, the important assertion is that the ACL gate did not block."""
    d = two_isolated_users
    client = Client()
    client.force_login(d["userB"])

    response = client.post(
        "/chat/api/pusher/auth/",
        data={
            "socket_id": "1234.5678",
            "channel_name": f"private-group-{d['sessionB']['id']}",
        },
    )
    assert response.status_code in (200, 403), f"unexpected status {response.status_code}"
    if response.status_code == 403:
        body = response.json()
        assert body.get("error") == "Auth failed", f"owner was rejected by ACL, not by Pusher: {body}"


def test_pusher_auth_rejects_spoofed_user_channel(two_isolated_users):
    """User A posting channel_name=private-user-<B.profile.pk> must be 403."""
    d = two_isolated_users
    client = Client()
    client.force_login(d["userA"])

    response = client.post(
        "/chat/api/pusher/auth/",
        data={
            "socket_id": "1234.5678",
            "channel_name": f"private-user-{d['profileB'].pk}",
        },
    )
    assert response.status_code == 403


def test_pusher_auth_rejects_unknown_channel_prefix(two_isolated_users):
    """A channel_name that is not private-group-* or private-user-* is 403."""
    d = two_isolated_users
    client = Client()
    client.force_login(d["userA"])

    response = client.post(
        "/chat/api/pusher/auth/",
        data={
            "socket_id": "1234.5678",
            "channel_name": "presence-admin-debug",
        },
    )
    assert response.status_code == 403
