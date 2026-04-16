"""Remove orphan :User nodes that no longer map to any Postgres UserProfile.

Context: before the `_user_id` fallback fix, writes could land on a :User node
whose id was Django auth.User.pk rather than UserProfile.pk. Those nodes are
now unreachable by any live code path but still hold old session/message
content. This script surgically removes them.

Default is DRY-RUN. Pass --execute to actually delete.

Companion to scripts/audit_neo4j_user_orphans.py (which only reports).

Usage:
    python scripts/cleanup_neo4j_user_orphans.py                # dry-run
    python scripts/cleanup_neo4j_user_orphans.py --execute       # perform delete
    python scripts/cleanup_neo4j_user_orphans.py --include-null  # also handle id=null
"""
import argparse
import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "memoria.settings.dev")
django.setup()

from app.services import neo4j_memory as neo4j
from app.users.models import UserProfile


def _find_orphans(include_null: bool):
    rows = neo4j._run_query(
        """
        MATCH (u:User)
        RETURN u.id AS neo4jId,
               u.username AS username,
               size([(u)-[:CREATED]->(:Session) | 1]) AS ownedSessions,
               size([(u)-[:MEMBER_OF]->(:Session) | 1]) AS memberSessions,
               size([(u)-[:OWNS]->(:Agent) | 1]) AS agents,
               size([(u)-[:HAS_MEMORY]->(:Memory) | 1]) AS memory
        """,
        {},
    )
    livePks = {str(pk) for pk in UserProfile.objects.values_list("pk", flat=True)}
    orphans = []
    for row in rows:
        nid = row.get("neo4jId")
        nidStr = str(nid) if nid is not None else None
        if nidStr is None:
            if include_null:
                orphans.append(row)
            continue
        if nidStr not in livePks:
            orphans.append(row)
    return orphans


def _purge(neo4j_id, row):
    """Remove a single orphan :User and everything it owns.

    Falls back to a DETACH DELETE on the :User node alone if the cascade
    helper does not exist or fails — the :User node itself must disappear
    so it can never be re-read via any stale code path."""
    if hasattr(neo4j, "delete_user_cascade"):
        try:
            neo4j.delete_user_cascade(str(neo4j_id))
            return "cascaded"
        except Exception:
            pass
    neo4j._run_query(
        "MATCH (u:User {id: $id}) DETACH DELETE u",
        {"id": str(neo4j_id)},
    )
    return "detached"


def _purge_null_row():
    neo4j._run_query(
        "MATCH (u:User) WHERE u.id IS NULL DETACH DELETE u",
        {},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Actually delete. Default is dry-run.")
    parser.add_argument("--include-null", action="store_true", help="Also purge :User nodes whose id is NULL")
    args = parser.parse_args()

    orphans = _find_orphans(args.include_null)
    if not orphans:
        print("No orphan :User nodes found. Nothing to do.")
        return 0

    totalSessions = sum((o.get("ownedSessions") or 0) for o in orphans)
    totalMembers = sum((o.get("memberSessions") or 0) for o in orphans)
    totalAgents = sum((o.get("agents") or 0) for o in orphans)
    totalMemory = sum((o.get("memory") or 0) for o in orphans)

    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"[{mode}] Found {len(orphans)} orphan :User nodes")
    print(f"Owned sessions: {totalSessions} (will be DELETED including all messages)")
    print(f"Member edges:   {totalMembers} (only the edge is removed; target session preserved)")
    print(f"Agents owned:   {totalAgents} (DELETED)")
    print(f"Memories owned: {totalMemory} (DELETED)")
    print()
    print(f"{'id':<10}{'owned':>6}{'member':>7}{'agents':>7}{'memory':>7}")
    for o in orphans:
        nid = o.get("neo4jId")
        print(
            f"{str(nid or 'NULL'):<10}"
            f"{o.get('ownedSessions') or 0:>6}"
            f"{o.get('memberSessions') or 0:>7}"
            f"{o.get('agents') or 0:>7}"
            f"{o.get('memory') or 0:>7}"
        )

    if not args.execute:
        print()
        print("This was a dry run. Re-run with --execute to actually delete.")
        return 0

    print()
    print("Executing...")
    deleted = 0
    for o in orphans:
        nid = o.get("neo4jId")
        if nid is None:
            _purge_null_row()
            print(f"  - NULL-id row: detached")
            deleted += 1
            continue
        mode = _purge(nid, o)
        print(f"  - id={nid}: {mode}")
        deleted += 1

    print()
    print(f"Removed {deleted} orphan :User nodes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
