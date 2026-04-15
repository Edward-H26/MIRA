from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Audit whether Django UserProfile.pk and auth.User.pk are aligned for every user. "
        "Divergence indicates that passing profile.user_id to Neo4j (used only for "
        "MemoryBullet.learnerId) points to a different logical identifier than profile.pk "
        "(used everywhere else). Read-only; no writes."
    )

    def handle(self, *args, **options):
        from app.users.models import UserProfile

        total = 0
        aligned = 0
        diverged = []

        profiles = UserProfile.objects.select_related("user").order_by("pk").all()
        for p in profiles:
            total += 1
            userPk = getattr(p.user, "pk", None)
            if userPk == p.pk:
                aligned += 1
            else:
                diverged.append({
                    "profile_pk": p.pk,
                    "user_pk": userPk,
                    "username": getattr(p.user, "username", "") if p.user else "",
                    "email": getattr(p.user, "email", "") if p.user else "",
                    "display_name": p.display_name or "",
                })

        self.stdout.write(self.style.MIGRATE_HEADING("User-identity alignment audit"))
        self.stdout.write(f"  profiles scanned: {total}")
        self.stdout.write(f"  aligned (profile.pk == user.pk): {aligned}")
        self.stdout.write(f"  diverged:                       {len(diverged)}")

        if diverged:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Divergent profiles:"))
            for row in diverged:
                self.stdout.write(
                    "  profile.pk={profile_pk} user.pk={user_pk} "
                    "username={username!r} display_name={display_name!r}".format(**row)
                )
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "Action required: Neo4j MemoryBullets store learnerId = profile.user_id "
                "(auth.User.pk), but every other Neo4j entity keys off profile.pk. "
                "For the divergent profiles above, their existing bullets are keyed by "
                "auth.User.pk while their Neo4j User node is keyed by UserProfile.pk. "
                "Before standardizing on profile.pk in code, run a data migration to "
                "rewrite those MemoryBullet.learnerId values."
            ))
        else:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(
                "No divergence detected. profile.pk == auth.User.pk for every user. "
                "Safe to swap 'learner_id=profile.user_id' callsites to "
                "'learner_id=profile.pk' without data migration."
            ))
