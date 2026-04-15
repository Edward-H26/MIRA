import json
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = (
        "Emit a single-shot JSON metrics snapshot for outbox health and "
        "Neo4j query latencies. Designed to be piped to a Prometheus "
        "text-format exporter, uptime check, or logged for operator review."
    )

    def add_arguments(self, parser):
        parser.add_argument("--format", choices=["json", "prometheus"], default="json")
        parser.add_argument("--stale-seconds", type=int, default=60,
                            help="Pending events older than this count as stale.")

    def handle(self, *args, **options):
        from app.chat.models.outbox_event import OutboxEvent

        staleCutoff = timezone.now() - timedelta(seconds=int(options.get("stale_seconds") or 60))

        metrics = {
            "outbox_pending_total": OutboxEvent.objects.filter(
                status=OutboxEvent.STATUS_PENDING,
            ).count(),
            "outbox_pending_stale_total": OutboxEvent.objects.filter(
                status=OutboxEvent.STATUS_PENDING,
                created_at__lt=staleCutoff,
            ).count(),
            "outbox_failed_total": OutboxEvent.objects.filter(
                status=OutboxEvent.STATUS_FAILED,
            ).count(),
            "outbox_applied_total": OutboxEvent.objects.filter(
                status=OutboxEvent.STATUS_APPLIED,
            ).count(),
        }

        try:
            from app.services import neo4j_memory as neo4j
            import time
            driver = neo4j._get_driver()
            if driver is not None:
                database = neo4j._get_database()
                with driver.session(database=database) as sess:
                    t = time.monotonic()
                    sess.run("RETURN 1 AS ok").single()
                    metrics["neo4j_ping_ms"] = int((time.monotonic() - t) * 1000)

                    t = time.monotonic()
                    sess.run(
                        "MATCH (s:DjangoSession) RETURN count(s) AS c"
                    ).single()
                    metrics["neo4j_django_sessions_total"] = int(
                        (time.monotonic() - t) * 1000
                    )
            else:
                metrics["neo4j_ping_ms"] = -1
        except Exception as exc:
            metrics["neo4j_error"] = str(exc)[:200]

        fmt = options.get("format") or "json"
        if fmt == "prometheus":
            for k, v in metrics.items():
                if isinstance(v, (int, float)):
                    self.stdout.write(f"memoria_{k} {v}")
                else:
                    safe = str(v).replace('"', r'\"')
                    self.stdout.write(f"memoria_{k}_info {{value=\"{safe}\"}} 1")
        else:
            self.stdout.write(json.dumps(metrics))
