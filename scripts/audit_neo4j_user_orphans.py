"""Audit :User nodes in Neo4j whose id does not map to a live UserProfile.

Runs read-only against Aura. Used to surface cross-user-leak aftermath:
rows that may have been written under an id that belonged to another user,
or that belonged to a Django-User.pk rather than the canonical
UserProfile.pk. Does not delete anything — operator reviews the report.

Usage:
    python scripts/audit_neo4j_user_orphans.py
    python scripts/audit_neo4j_user_orphans.py --json
"""
import argparse
import json
import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "memoria.settings.dev")
django.setup()

from app.services import neo4j_memory as neo4j
from app.users.models import UserProfile


def _fetch_neo4j_users():
    return neo4j._run_query(
        """
        MATCH (u:User)
        RETURN u.id AS neo4jId,
               u.username AS username,
               u.displayName AS displayName,
               size([(u)-[:CREATED]->(:Session) | 1]) AS ownedSessions,
               size([(u)-[:MEMBER_OF]->(:Session) | 1]) AS memberSessions,
               size([(u)-[:OWNS]->(:Agent) | 1]) AS agentCount,
               size([(u)-[:HAS_MEMORY]->(:Memory) | 1]) AS memoryCount
        """,
        {},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a human report")
    args = parser.parse_args()

    livePkSet = {str(pk) for pk in UserProfile.objects.values_list("pk", flat=True)}
    neo4jUsers = _fetch_neo4j_users()

    orphans = []
    for row in neo4jUsers:
        neo4jId = str(row.get("neo4jId", "") or "")
        if neo4jId and neo4jId not in livePkSet:
            orphans.append({
                "neo4jId": neo4jId,
                "username": row.get("username"),
                "displayName": row.get("displayName"),
                "ownedSessions": row.get("ownedSessions") or 0,
                "memberSessions": row.get("memberSessions") or 0,
                "agentCount": row.get("agentCount") or 0,
                "memoryCount": row.get("memoryCount") or 0,
            })

    if args.json:
        print(json.dumps({
            "neo4jUserCount": len(neo4jUsers),
            "postgresProfileCount": len(livePkSet),
            "orphanCount": len(orphans),
            "orphans": orphans,
        }, indent=2))
    else:
        print(f"Neo4j :User nodes: {len(neo4jUsers)}")
        print(f"Postgres UserProfile rows: {len(livePkSet)}")
        print(f"Orphan :User nodes (no matching UserProfile.pk): {len(orphans)}")
        if orphans:
            print()
            print(f"{'neo4jId':<16} {'username':<24} {'owned':>6} {'member':>7} {'agents':>7} {'memory':>7}")
            for o in orphans:
                print(
                    f"{o['neo4jId']:<16} "
                    f"{str(o['username'] or '')[:22]:<24} "
                    f"{o['ownedSessions']:>6} "
                    f"{o['memberSessions']:>7} "
                    f"{o['agentCount']:>7} "
                    f"{o['memoryCount']:>7}"
                )

    return 0 if not orphans else 1


if __name__ == "__main__":
    sys.exit(main())
