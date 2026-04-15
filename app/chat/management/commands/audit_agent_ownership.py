import re

from django.core.management.base import BaseCommand

from app.services import neo4j_memory as neo4j


AGENT_NAME_PATTERN = re.compile(r"^(?P<display>.+?)'s\s+Agent\s*$", re.IGNORECASE)


class Command(BaseCommand):
    help = (
        "Cross-check Neo4j Agent.name against the owning User's Django display_name. "
        "Finds agents whose auto-generated name ('X's Agent') references a display name "
        "different from the current owner, indicating stale display_name at agent-creation "
        "time or a genuine cross-user ownership bug. Read-only; no writes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--show-matching",
            action="store_true",
            help="Also print agents where names correctly match the owner.",
        )

    def handle(self, *args, **options):
        from app.users.models import UserProfile

        driver = neo4j._get_driver()
        if driver is None:
            self.stdout.write(self.style.ERROR(
                "Neo4j driver unavailable. Set NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD."
            ))
            return

        database = neo4j._get_database()
        rows = []
        with driver.session(database=database) as session:
            result = session.run(
                """
                MATCH (u:User)-[:OWNS]->(a:Agent)
                RETURN a.id AS agent_id, a.name AS agent_name,
                       a.isActive AS is_active, a.createdAt AS created_at,
                       u.id AS owner_neo_id
                ORDER BY a.createdAt
                """
            )
            for r in result:
                rows.append({
                    "agent_id": r["agent_id"],
                    "agent_name": r["agent_name"] or "",
                    "is_active": r["is_active"],
                    "created_at": str(r["created_at"]) if r["created_at"] else "",
                    "owner_neo_id": r["owner_neo_id"],
                })

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Agent ownership audit ({len(rows)} agent(s) in Neo4j)"
        ))

        profiles_by_pk = {
            str(p.pk): p for p in UserProfile.objects.select_related("user").all()
        }

        mismatches = []
        orphans = []
        matches = []

        for row in rows:
            neoId = str(row["owner_neo_id"])
            profile = profiles_by_pk.get(neoId)
            if profile is None:
                orphans.append(row)
                continue

            display = (profile.display_name or "").strip()
            username = getattr(profile.user, "username", "") if profile.user else ""
            fullName = profile.user.get_full_name().strip() if profile.user else ""
            ownerIdentities = {
                v for v in (display, username, fullName, display.split(" ")[0] if display else "")
                if v
            }

            match = AGENT_NAME_PATTERN.match(row["agent_name"])
            if not match:
                matches.append({**row, "owner_display": display})
                continue

            nameOwner = match.group("display").strip()
            if any(nameOwner == ident or nameOwner.lower() == ident.lower() for ident in ownerIdentities):
                matches.append({**row, "owner_display": display})
            else:
                mismatches.append({
                    **row,
                    "owner_display": display,
                    "owner_username": username,
                    "owner_full_name": fullName,
                    "name_references": nameOwner,
                })

        self.stdout.write(f"  matched cleanly: {len(matches)}")
        self.stdout.write(f"  orphans (owner not in Django): {len(orphans)}")
        self.stdout.write(f"  name/owner mismatches:         {len(mismatches)}")

        if orphans:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Orphaned Neo4j agents (no Django profile):"))
            for o in orphans:
                self.stdout.write(
                    f"  agent_id={o['agent_id']} name={o['agent_name']!r} "
                    f"owner_neo_id={o['owner_neo_id']}"
                )

        if mismatches:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "Agents whose name references a different identity than their owner:"
            ))
            for m in mismatches:
                self.stdout.write(
                    f"  agent_id={m['agent_id']}"
                )
                self.stdout.write(
                    f"    agent.name         = {m['agent_name']!r}"
                )
                self.stdout.write(
                    f"    name references    = {m['name_references']!r}"
                )
                self.stdout.write(
                    f"    owner profile.pk   = {m['owner_neo_id']}"
                )
                self.stdout.write(
                    f"    owner display_name = {m['owner_display']!r}"
                )
                self.stdout.write(
                    f"    owner username     = {m['owner_username']!r}"
                )
                self.stdout.write(
                    f"    owner full_name    = {m['owner_full_name']!r}"
                )
                self.stdout.write(
                    f"    is_active          = {m['is_active']}"
                )
                self.stdout.write(
                    f"    created_at         = {m['created_at']}"
                )

        if options.get("show_matching") and matches:
            self.stdout.write("")
            self.stdout.write("Matching agents:")
            for m in matches:
                self.stdout.write(
                    f"  agent_id={m['agent_id']} name={m['agent_name']!r} "
                    f"owner={m['owner_display']!r}"
                )

        self.stdout.write("")
        if not mismatches and not orphans:
            self.stdout.write(self.style.SUCCESS(
                "No ownership/name discrepancies found. The 'wrong agent' symptom must "
                "therefore come from a display-layer bug, not data-level corruption."
            ))
        else:
            self.stdout.write(self.style.WARNING(
                "Run: python manage.py repair_agent_names --agent-id=<id> "
                "(see --help for strategies). Dry-run by default."
            ))
