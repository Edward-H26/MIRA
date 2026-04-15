# Storage Redesign — Split-Stores Architecture

> Status: design document. Round 1 (surgical fixes) shipped. Round 2 (outbox pattern) scaffolded. Round 3 (this doc) describes the target architecture to pursue incrementally.

## Motivation

The current deployment serves five distinct workloads on a single Neo4j instance plus a Django ORM that is partly canonical, partly ceremonial:

1. **Auth** (Django `auth.User`, `UserProfile`) — Postgres
2. **Session store** (Django HTTP sessions) — Neo4j `DjangoSession` nodes
3. **Chat domain** (Agents, Sessions, Messages) — Neo4j, written after migration, never synced back
4. **Memory graph** (Memory, MemoryBullet, AceMemoryState) — Neo4j, dual-written from Django
5. **Streaming fan-out** (agent generation broadcasts) — in-process Python, single worker only

Each workload has a different ideal access pattern, durability profile, and scaling story. Conflating them in one store has produced the exact bugs this project has been chasing: camelCase/snake_case mismatches, identifier drift, stale display names, Kevin-sees-Edward cross-user confusion, per-process broadcast state, unbounded scan on session load.

## Target Architecture

| Workload | Target store | Rationale |
|---|---|---|
| Auth (users, profiles, OAuth tokens) | **Postgres** | ACID, battle-tested Django backends |
| HTTP sessions | **Redis** (or signed cookies) | O(1) keyed KV, TTL-native, far cheaper than a graph query per request |
| Chat domain (agents, sessions, messages) | **Postgres** (canonical) + Neo4j (derived read view) | Row-level security, simple transactions, massive write volume |
| Memory graph | **Neo4j** | Actual graph traversal workload: skill dependencies, cross-agent memory |
| Vector embeddings | **pgvector** (Postgres extension) | ANN indexes are purpose-built; no reason to store them in a graph DB |
| Streaming fan-out | **Redis Streams** or **NATS JetStream** | Enables multi-worker horizontal scaling with sticky sessions |

## Migration Sequence

Run in this order. Each step is independently valuable; pause between steps to observe production.

### Phase A — Exit Neo4j as session store (1 week)

1. Add Redis to the deployment (Render, Upstash, etc).
2. Set `SESSION_ENGINE = "django.contrib.sessions.backends.cache"` with Redis cache backend.
3. Remove `neo4j_session_backend` and delete `cleanup_expired_sessions` once drained.

Observable win: p50 request latency drops because every authenticated request skips a graph scan.

### Phase B — Move chat domain writes to Postgres + outbox (2 weeks)

1. Re-enable Django ORM writes on `Agent`, `Session`, `Message`, `SessionMember`.
2. Every write path wraps in `@transaction.atomic` and calls `outbox.enqueue(...)` alongside the Postgres mutation.
3. `drain_outbox` worker keeps Neo4j in sync.
4. Delete the direct `neo4j.create_session`, `neo4j.create_message`, `neo4j.create_agent` callsites from views.
5. View layer now reads Agent/Session/Message from Postgres; Neo4j is the derived read view used only for cross-user traversal (e.g., "agents my teammates use").

Observable win: write atomicity. Kevin-sees-Edward class of bugs cannot recur.

### Phase C — Split memory graph cleanly (2 weeks)

1. Decide the Memory vs AceMemoryState boundary. Merge if they serve the same retrieval; separate with clear interfaces if not.
2. Move `MemoryBullet.embedding` to a pgvector column; rebuild similarity search via `SELECT ... ORDER BY embedding <=> $query LIMIT 10`.
3. Keep `MemoryBullet`, `HAS_SKILL`, `HAS_BULLET`, `VOTED` edges in Neo4j for traversal only.
4. Retrieval pipeline: pgvector for semantic match, Neo4j for structural expansion ("bullets connected to this skill").

Observable win: retrieval latency drops; Neo4j only holds what it is good at.

### Phase D — Streaming on Redis Streams (1 week)

1. Replace `_GenerationBroadcast` in-process fanout with a Redis Streams producer/consumer.
2. Gunicorn can now run `--workers 4` with sticky sessions at the load balancer.
3. Add health check that consumes a heartbeat message through the Redis path so worker isolation is verified end-to-end.

Observable win: horizontal scale-out unlocked; one crashed worker no longer loses in-flight streams.

## Non-Goals

- **No ORM replacement.** Django ORM stays as the Postgres layer.
- **No microservices split.** Single deployable; just more stores.
- **No graph database abandonment.** Neo4j still holds the traversal graph — it just stops being asked to serve HTTP sessions and transactional message writes.

## Identifier Standardization (cross-cutting)

Standardized on `UserProfile.pk` as the sole Neo4j-facing identifier. `auth.User.pk` is never used as a Neo4j key. The 9 legacy `profile.user_id` callsites were swapped to `profile.pk` in Round 1, with `migrate_learner_id_to_profile_pk` as the data safety net.

## Property Naming (cross-cutting)

Neo4j properties use `camelCase`. Python-side lookups must match. The `update_agent` / `update_session` field_map dicts are the sole place where snake_case → camelCase translation happens. New templates and Cypher queries should reference camelCase directly.

## Rollback Strategy

Each phase is reversible for 30 days post-deployment:
- Phase A: keep Neo4j session backend around under a feature flag until Redis has proven stable.
- Phase B: the outbox worker can be disabled and direct Neo4j writes re-enabled from Git history.
- Phase C: pgvector columns can coexist with Neo4j embeddings until confidence is earned.
- Phase D: `_GenerationBroadcast` in-process fallback stays in the code as a single-worker escape hatch.

## Operational Posture

- Prometheus metrics on every `_run_query` call (operation, latency, result-size).
- Outbox drain lag alert if `pending` events older than 60s appear.
- Redis Streams consumer lag alert.
- Dashboard panels for Neo4j query-time percentiles and outbox backlog depth.
