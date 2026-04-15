from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Run periodic Neo4j cleanup tasks: expired Django sessions, stale "
        "outbox events, any other scheduled housekeeping. Designed to run "
        "from a cron / scheduler every few minutes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-sessions",
            action="store_true",
            help="Skip DjangoSession cleanup.",
        )
        parser.add_argument(
            "--skip-outbox",
            action="store_true",
            help="Skip archiving applied OutboxEvent rows older than 7 days.",
        )
        parser.add_argument(
            "--outbox-retention-days",
            type=int,
            default=7,
            help="Delete applied OutboxEvent rows older than N days (default 7).",
        )

    def handle(self, *args, **options):
        from app.services import neo4j_memory as neo4j

        total = {}

        if not options.get("skip_sessions"):
            try:
                removed = neo4j.cleanup_expired_sessions()
                total["expired_sessions"] = int(removed or 0)
                self.stdout.write(
                    f"  expired_sessions removed: {total['expired_sessions']}"
                )
            except Exception as exc:
                self.stdout.write(self.style.ERROR(
                    f"  expired_sessions FAILED: {exc}"
                ))

        if not options.get("skip_outbox"):
            from datetime import timedelta
            from django.utils import timezone
            from app.chat.models.outbox_event import OutboxEvent

            cutoff = timezone.now() - timedelta(days=int(options.get("outbox_retention_days") or 7))
            try:
                removed, _ = (
                    OutboxEvent.objects.filter(
                        status=OutboxEvent.STATUS_APPLIED,
                        applied_at__lt=cutoff,
                    ).delete()
                )
                total["outbox_archived"] = int(removed or 0)
                self.stdout.write(
                    f"  outbox_archived (applied < {options.get('outbox_retention_days')} days): "
                    f"{total['outbox_archived']}"
                )
            except Exception as exc:
                self.stdout.write(self.style.ERROR(
                    f"  outbox_archived FAILED: {exc}"
                ))

        self.stdout.write(self.style.SUCCESS(
            f"cleanup_neo4j done: {total}"
        ))
