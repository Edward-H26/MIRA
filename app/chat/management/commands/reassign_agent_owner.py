from django.core.management.base import BaseCommand, CommandError

from app.services import neo4j_memory as neo4j


class Command(BaseCommand):
    help = (
        "Reassign a Neo4j Agent's OWNS relationship from one user to another. "
        "Use ONLY when audit_agent_ownership reports genuine cross-user "
        "corruption (agent owned by wrong user, not just stale display_name). "
        "Dry-run by default; --apply executes. Preserves all Agent data; "
        "only the OWNS edge and any downstream permission-scoped relationships "
        "are updated."
    )

    def add_arguments(self, parser):
        parser.add_argument("--agent-id", type=str, required=True)
        parser.add_argument("--new-owner-profile-pk", type=str, required=True,
                            help="UserProfile.pk of the new owner (matches Neo4j User.id).")
        parser.add_argument("--apply", action="store_true",
                            help="Actually execute the reassignment.")

    def handle(self, *args, **options):
        from app.users.models import UserProfile

        agentId = options["agent_id"].strip()
        newOwnerPk = str(options["new_owner_profile_pk"]).strip()
        apply = bool(options.get("apply"))

        if not agentId or not newOwnerPk:
            raise CommandError("--agent-id and --new-owner-profile-pk are both required")

        try:
            newProfile = UserProfile.objects.select_related("user").get(pk=int(newOwnerPk))
        except (UserProfile.DoesNotExist, ValueError, TypeError):
            raise CommandError(f"UserProfile pk={newOwnerPk!r} not found in Django")

        driver = neo4j._get_driver()
        if driver is None:
            raise CommandError("Neo4j driver unavailable.")
        database = neo4j._get_database()

        with driver.session(database=database) as sess:
            current = sess.run(
                """
                MATCH (u:User)-[r:OWNS]->(a:Agent {id: $agentId})
                RETURN u.id AS owner_id, a.name AS agent_name
                """,
                {"agentId": agentId},
            ).single()

            if current is None:
                raise CommandError(
                    f"Agent id={agentId!r} has no OWNS edge. Cannot reassign."
                )

            oldOwnerId = str(current["owner_id"])
            agentName = current["agent_name"]

        if oldOwnerId == newOwnerPk:
            self.stdout.write(self.style.WARNING(
                f"Agent {agentId} already owned by profile.pk={newOwnerPk}. No-op."
            ))
            return

        self.stdout.write(self.style.MIGRATE_HEADING("Reassignment plan"))
        self.stdout.write(f"  agent_id:        {agentId}")
        self.stdout.write(f"  agent_name:      {agentName!r}")
        self.stdout.write(f"  current owner:   profile.pk={oldOwnerId}")
        self.stdout.write(f"  new owner:       profile.pk={newOwnerPk} "
                          f"username={newProfile.user.username!r} "
                          f"display={newProfile.display_name!r}")

        if not apply:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "Dry-run. Re-run with --apply to execute."
            ))
            return

        with driver.session(database=database) as sess:
            sess.run(
                """
                MERGE (newU:User {id: $newOwnerId})
                ON CREATE SET newU.createdAt = datetime()
                WITH newU
                MATCH (oldU:User)-[r:OWNS]->(a:Agent {id: $agentId})
                WHERE oldU.id <> $newOwnerId
                DELETE r
                MERGE (newU)-[:OWNS]->(a)
                """,
                {"agentId": agentId, "newOwnerId": newOwnerPk},
            )
            verify = sess.run(
                """
                MATCH (u:User)-[:OWNS]->(a:Agent {id: $agentId})
                RETURN u.id AS owner_id
                """,
                {"agentId": agentId},
            ).single()

        if verify and str(verify["owner_id"]) == newOwnerPk:
            self.stdout.write(self.style.SUCCESS(
                f"Reassigned. agent {agentId} is now owned by profile.pk={newOwnerPk}."
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f"Reassignment verification FAILED. "
                f"Current owner: {verify and verify['owner_id']!r}"
            ))
