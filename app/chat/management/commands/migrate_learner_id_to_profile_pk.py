from django.core.management.base import BaseCommand, CommandError

from app.services import neo4j_memory as neo4j


class Command(BaseCommand):
    help = (
        "For each Django UserProfile whose pk != user.pk (i.e. divergent identifiers), "
        "rewrite MemoryBullet.learnerId from auth.User.pk to UserProfile.pk in Neo4j. "
        "Must be run BEFORE swapping learner_id callsites in code. "
        "Defaults to dry-run; pass --apply to execute."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually write changes. Without this flag, prints the plan only.",
        )

    def handle(self, *args, **options):
        from app.users.models import UserProfile

        apply = bool(options.get("apply"))

        driver = neo4j._get_driver()
        if driver is None:
            raise CommandError("Neo4j driver unavailable.")
        database = neo4j._get_database()

        divergent = []
        for p in UserProfile.objects.select_related("user").order_by("pk").all():
            userPk = getattr(p.user, "pk", None)
            if userPk is None or userPk == p.pk:
                continue
            divergent.append({
                "profile_pk": str(p.pk),
                "user_pk": str(userPk),
                "username": getattr(p.user, "username", "") if p.user else "",
            })

        if not divergent:
            self.stdout.write(self.style.SUCCESS(
                "No divergent profiles found. MemoryBullet.learnerId rewrite not required."
            ))
            return

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Found {len(divergent)} divergent profile(s). Planning learnerId rewrites."
        ))

        plan = []
        with driver.session(database=database) as sess:
            for row in divergent:
                result = sess.run(
                    """
                    MATCH (mb:MemoryBullet {learnerId: $oldLearner})
                    RETURN count(mb) AS cnt
                    """,
                    {"oldLearner": row["user_pk"]},
                )
                rec = result.single()
                cnt = int(rec["cnt"]) if rec else 0
                plan.append({**row, "bullet_count": cnt})

        for p in plan:
            self.stdout.write(
                f"  profile.pk={p['profile_pk']} user.pk={p['user_pk']} "
                f"username={p['username']!r} bullets_to_rewrite={p['bullet_count']}"
            )

        if not apply:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "Dry-run. Re-run with --apply to rewrite learnerId on the bullets above."
            ))
            return

        written = 0
        with driver.session(database=database) as sess:
            for p in plan:
                if p["bullet_count"] == 0:
                    continue
                res = sess.run(
                    """
                    MATCH (mb:MemoryBullet {learnerId: $oldLearner})
                    SET mb.learnerId = $newLearner
                    RETURN count(mb) AS cnt
                    """,
                    {"oldLearner": p["user_pk"], "newLearner": p["profile_pk"]},
                )
                rec = res.single()
                cnt = int(rec["cnt"]) if rec else 0
                written += cnt
                self.stdout.write(
                    f"  rewrote {cnt} bullet(s) for profile.pk={p['profile_pk']}"
                )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Applied. Total bullets rewritten: {written}."
        ))
