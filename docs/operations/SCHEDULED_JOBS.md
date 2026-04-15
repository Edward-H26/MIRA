# Scheduled Jobs

Production needs two always-on processes beyond the web server: the outbox drain worker and a periodic cleanup driver. Both are Django management commands.

## 1. Outbox drain worker (always-on)

Projects pending `OutboxEvent` rows into Neo4j. Run as a long-lived process.

```bash
python manage.py drain_outbox --loop
```

Render configuration example (separate background worker service in `render.yaml`):

```yaml
services:
  - type: worker
    name: outbox-drain
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: python manage.py drain_outbox --loop
    envVarsFromGroup: memoria-env
```

The worker sleeps 1 second between empty batches and processes up to 50 events per batch (configurable via `--batch-size`). Events retry up to 5 times before being marked `FAILED` (configurable via `--max-attempts`).

## 2. Periodic cleanup (cron every 5 minutes)

Cleans up expired HTTP sessions in Neo4j and archives applied outbox rows older than 7 days.

```bash
python manage.py cleanup_neo4j
```

Render cron configuration:

```yaml
  - type: cron
    name: neo4j-cleanup
    env: python
    buildCommand: pip install -r requirements.txt
    schedule: "*/5 * * * *"
    command: python manage.py cleanup_neo4j
    envVarsFromGroup: memoria-env
```

The cron archives applied outbox rows older than N days (default 7, override with `--outbox-retention-days`). Skip individual phases with `--skip-sessions` or `--skip-outbox`.

## 3. Optional monitoring queries

Add these as uptime pings or dashboard widgets.

### Outbox backlog depth
```bash
python manage.py shell -c "
from app.chat.models.outbox_event import OutboxEvent
from datetime import timedelta
from django.utils import timezone

pending = OutboxEvent.objects.filter(status=OutboxEvent.STATUS_PENDING).count()
stale = OutboxEvent.objects.filter(
    status=OutboxEvent.STATUS_PENDING,
    created_at__lt=timezone.now() - timedelta(minutes=1),
).count()
failed = OutboxEvent.objects.filter(status=OutboxEvent.STATUS_FAILED).count()
print(f'pending={pending} stale(>1min)={stale} failed={failed}')
"
```

Alert threshold suggestions:
- `pending > 1000` — worker is falling behind, scale up
- `stale > 100` — worker has likely crashed, restart
- `failed > 0` — investigate; inspect `OutboxEvent.last_error` for root cause

### Neo4j query latency spot check
```bash
python manage.py shell -c "
import time
from app.services import neo4j_memory as neo4j

t = time.monotonic()
neo4j.get_sessions_for_user('1', limit=1)
print(f'sessions_for_user 1 row: {(time.monotonic()-t)*1000:.1f}ms')

t = time.monotonic()
neo4j.get_unread_notification_count('1')
print(f'unread_count: {(time.monotonic()-t)*1000:.1f}ms')
"
```

Both should complete in under 100ms with proper indexes; sustained values above 500ms indicate index drift or Neo4j load issues.

## 4. Failure playbook

### If the outbox backlog grows faster than it drains
1. Check `drain_outbox` worker is actually running: `ps aux | grep drain_outbox` on the worker instance
2. Increase `--batch-size` to 200
3. If still growing, scale workers horizontally (multiple `drain_outbox` processes are safe because `.order_by("created_at")[:batch]` plus `save()` produces independent row locks)

### If specific operations consistently fail
1. Query failing events: `OutboxEvent.objects.filter(status="failed").values("operation", "last_error")`
2. Common causes: schema drift (new field unknown to Cypher), Neo4j authorization issues
3. After fixing root cause, reset events to pending: `.update(status="pending", attempts=0)`

### If sessions aren't expiring
1. Verify cron is running: check Render logs for `cleanup_neo4j` invocations
2. Check Neo4j index on `DjangoSession.expireDate` exists: `SHOW INDEXES WHERE name = 'django_session_expire_idx'`
3. Manually run: `python manage.py cleanup_neo4j` and check the output
