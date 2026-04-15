import re

from django.core.management.base import BaseCommand, CommandError

from app.services import neo4j_memory as neo4j


AGENT_NAME_PATTERN = re.compile(r"^(?P<display>.+?)'s\s+Agent\s*$", re.IGNORECASE)


class Command(BaseCommand):
    help = (
        "Repair Neo4j Agent.name when the auto-generated 'X's Agent' pattern "
        "references an X that differs from the owner's current display_name. "
        "Defaults to dry-run; pass --apply to execute. Does NOT change OWNS relationships."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually write changes. Without this flag, prints the plan only.",
        )
        parser.add_argument(
            "--agent-id",
            type=str,
            default="",
            help="Repair only this specific agent id (optional).",
        )
        parser.add_argument(
            "--strategy",
            choices=["rename", "sync-profile"],
            default="rename",
            help=(
                "rename: overwrite agent.name to '{current_display_name}'s Agent'. "
                "sync-profile: update the owning UserProfile.display_name to what the "
                "agent name references (only safe if you trust the agent name)."
            ),
        )

    def handle(self, *args, **options):
        from app.users.models import UserProfile

        apply = bool(options.get("apply"))
        agentIdFilter = (options.get("agent_id") or "").strip()
        strategy = options.get("strategy") or "rename"

        driver = neo4j._get_driver()
        if driver is None:
            raise CommandError(
                "Neo4j driver unavailable. Set NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD."
            )

        database = neo4j._get_database()
        rows = []
        with driver.session(database=database) as session:
            if agentIdFilter:
                result = session.run(
                    """
                    MATCH (u:User)-[:OWNS]->(a:Agent {id: $agentId})
                    RETURN a.id AS agent_id, a.name AS agent_name,
                           u.id AS owner_neo_id
                    """,
                    {"agentId": agentIdFilter},
                )
            else:
                result = session.run(
                    """
                    MATCH (u:User)-[:OWNS]->(a:Agent)
                    RETURN a.id AS agent_id, a.name AS agent_name,
                           u.id AS owner_neo_id
                    ORDER BY a.createdAt
                    """
                )
            for r in result:
                rows.append({
                    "agent_id": r["agent_id"],
                    "agent_name": r["agent_name"] or "",
                    "owner_neo_id": r["owner_neo_id"],
                })

        if not rows:
            self.stdout.write(self.style.WARNING("No agents matched the filter."))
            return

        profiles_by_pk = {
            str(p.pk): p for p in UserProfile.objects.select_related("user").all()
        }

        planned = []
        for row in rows:
            profile = profiles_by_pk.get(str(row["owner_neo_id"]))
            if profile is None:
                continue

            display = (profile.display_name or "").strip()
            fullName = profile.user.get_full_name().strip() if profile.user else ""
            username = getattr(profile.user, "username", "") if profile.user else ""
            ownerIdentities = {v for v in (display, username, fullName) if v}

            match = AGENT_NAME_PATTERN.match(row["agent_name"])
            if not match:
                continue
            nameRefers = match.group("display").strip()
            if any(nameRefers == ident or nameRefers.lower() == ident.lower() for ident in ownerIdentities):
                continue

            newDisplay = display or fullName or username or "Assistant"
            newName = f"{newDisplay}'s Agent"

            planned.append({
                "agent_id": row["agent_id"],
                "old_name": row["agent_name"],
                "new_name": newName,
                "owner_pk": row["owner_neo_id"],
                "owner_current_display": display,
                "name_refers_to": nameRefers,
                "new_profile_display": nameRefers,
            })

        if not planned:
            self.stdout.write(self.style.SUCCESS(
                "No agent names need repair."
            ))
            return

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Repair plan ({len(planned)} agent(s)) — strategy: {strategy} — apply: {apply}"
        ))
        for p in planned:
            if strategy == "rename":
                self.stdout.write(
                    f"  agent_id={p['agent_id']} : {p['old_name']!r}  ->  {p['new_name']!r} "
                    f"(owner profile.pk={p['owner_pk']})"
                )
            else:
                self.stdout.write(
                    f"  UserProfile(pk={p['owner_pk']}).display_name "
                    f"{p['owner_current_display']!r}  ->  {p['new_profile_display']!r} "
                    f"(agent unchanged: {p['old_name']!r})"
                )

        if not apply:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "Dry-run (no writes). Re-run with --apply to execute."
            ))
            return

        written = 0
        with driver.session(database=database) as session:
            for p in planned:
                if strategy == "rename":
                    session.run(
                        """
                        MATCH (a:Agent {id: $agentId})
                        SET a.name = $name, a.updatedAt = datetime()
                        """,
                        {"agentId": p["agent_id"], "name": p["new_name"]},
                    )
                    written += 1
                else:
                    try:
                        profile = profiles_by_pk.get(str(p["owner_pk"]))
                        if profile is None:
                            continue
                        profile.display_name = p["new_profile_display"]
                        profile.save(update_fields=["display_name"])
                        written += 1
                    except Exception as exc:
                        self.stdout.write(self.style.ERROR(
                            f"  FAILED profile.pk={p['owner_pk']}: {exc}"
                        ))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Applied {written} change(s)."))
