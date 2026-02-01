# Database Design Choices

This document provides comprehensive documentation of all database design decisions for the MEMORIA project, including naming conventions, architecture choices, and relationship strategies.

---

## Section 1: Naming Conventions

### 1.1 Project Names

| Name | Full Meaning | Usage |
|------|--------------|-------|
| **MEMORIA** | Memory Enhanced Multi-modal Orchestration Reasoning Intelligence Architecture | Product name, full system |
| **MIRA** | Memory Incremental Reasoning Architecture | Team name (Team 4), Django project configuration folder |
| **miramemoria** | Combined MIRA + MEMORIA | Repository/folder name |

### 1.2 Why These Names Were Chosen

**MEMORIA**
- Spanish/Latin for "memory"
- Reflects the core innovation: persistent adaptive memory that learns user patterns
- Acronym captures the multi-modal, orchestration, and reasoning capabilities
- Evokes the concept of collective memory that evolves over time

**MIRA**
- Acronym representing the incremental learning approach
- Spanish meaning: "look" or "see", implying transparent visibility into AI memory
- Short, memorable identifier for the team
- Symbolizes the system's ability to observe and learn from user interactions

**Combined Name (miramemoria)**
- Bridges team identity (MIRA) with product identity (MEMORIA)
- Creates unique, searchable repository name
- Reflects the dual nature: the team's vision (MIRA) building the memory system (MEMORIA)

### 1.3 Django Project and App Names

| Name | Type | Purpose | Naming Rationale |
|------|------|---------|------------------|
| `mira/` | Project config | Settings, URLs, WSGI/ASGI | Named after team; represents the project-level configuration |
| `memoria` | App | Main app wiring, URL routing | Named after product; serves as entry point that routes to domain apps |
| `chat` | App | Chat sessions, messages, memory | Descriptive; handles conversation and memory persistence |
| `billing` | App | Plans, subscriptions, payments | Descriptive; handles commerce and subscription logic |
| `users` | App | User profiles | Descriptive; extends Django auth with profile-specific fields |

### 1.4 AppConfig Class Names

| Config Class | App | Rationale |
|--------------|-----|-----------|
| `MiraConfig` | memoria | Bridges the memoria app to the MIRA project identity; the main app carries the team name |
| `ChatConfig` | chat | Standard Django convention; clear domain identification |
| `BillingConfig` | billing | Standard Django convention; clear domain identification |
| `UsersConfig` | users | Standard Django convention; clear domain identification |

### 1.5 Model Naming Conventions

**Model Classes (PascalCase)**
- `User` - User profile extension
- `Session` - Chat conversation container
- `Message` - Individual chat message
- `Memory` - User's memory container with access tracking
- `MemoryBullet` - Granular memory fact with scoring
- `Plan` - Subscription offering
- `Subscription` - User's active subscription
- `Payment` - Payment transaction record

**Field Names (snake_case)**
- Temporal: `created_at`, `updated_at`, `paid_at`, `last_accessed`
- Counters: `access_clock`, `helpful_count`, `harmful_count`, `strength`
- Relations: `user`, `session`, `memory`, `plan`, `subscription`
- Metadata: `memory_type`, `topic`, `concept`, `ttl_days`

**Choice Enums (UPPER_SNAKE_CASE)**
- `SEMANTIC`, `EPISODIC`, `PROCEDURAL` (MemoryType)
- `SYSTEM`, `USER`, `ASSISTANT` (Role)
- `MONTHLY`, `YEARLY` (Interval)
- `PENDING`, `SUCCEEDED`, `FAILED`, `CANCELLED` (Status)

**Database Table Names**
- Pattern: `{app_label}_{model_name}`
- Examples: `chat_session`, `chat_memory`, `billing_plan`, `users_user`

---

## Section 2: Architecture Decisions

### 2.1 Memory System Design

**Three Memory Types (MemoryBullet.memory_type)**

| Type | Value | Purpose | Decay Rate | Rationale |
|------|-------|---------|------------|-----------|
| SEMANTIC | 1 | Facts and concepts | 1% per access | Stable knowledge decays slowly |
| EPISODIC | 2 | Experiences and events | 5% per access | Events fade faster than facts |
| PROCEDURAL | 3 | Instructions and skills | 0.2% per access | Learned skills persist longest |

**Cognitive Psychology Basis**: This taxonomy mirrors human memory research. Procedural memories (how to ride a bike) persist longer than episodic memories (what you ate yesterday), which are more volatile than semantic facts (the capital of France).

**MemoryBullet Granularity Choice**
- Individual memory facts stored as separate bullets rather than monolithic blobs
- Benefits:
  - Fine-grained scoring (helpful_count, harmful_count per bullet)
  - Selective retrieval based on relevance
  - TTL-based expiration per bullet
  - Independent decay tracking
  - User can rate individual memories

**Memory Container (Memory model)**
- Groups related bullets under a single memory instance
- Tracks global access_clock for decay calculations
- Links to user for ownership and retrieval

### 2.2 Database Relationships and on_delete Strategies

| Model | Field | Relation | on_delete | Justification |
|-------|-------|----------|-----------|---------------|
| User | user | OneToOne to auth.User | CASCADE | Profile has no meaning without auth user; cascade to remove profile if auth user deleted |
| Session | user | FK to users.User | CASCADE | Sessions belong to users; cascade to remove sessions if user deleted |
| Memory | user | FK to users.User | CASCADE | Memories are user-specific; cascade to avoid orphaned memories |
| MemoryBullet | memory | FK to Memory | CASCADE | Bullets belong to memories; cascade to keep bullets in sync with parent |
| Message | session | FK to Session | CASCADE | Messages belong to sessions; cascade to remove messages with session |
| Subscription | user | FK to users.User | CASCADE | Subscriptions belong to users; cascade to remove if user deleted |
| Subscription | plan | FK to Plan | PROTECT | Prevent deleting plans that have active subscriptions; protects business data integrity |
| Payment | user | FK to users.User | CASCADE | Payments belong to users; cascade to remove if user deleted |
| Payment | subscription | FK to Subscription | SET_NULL | Keep payment history even if subscription removed; audit trail requirement |
| Payment | plan | FK to Plan | SET_NULL | Keep payment history even if plan removed; audit trail requirement |

**Strategy Summary**:
- **CASCADE**: Child data has no meaning without parent (profiles, sessions, messages, memories)
- **PROTECT**: Deletion would cause data integrity issues (plans with active subscriptions)
- **SET_NULL**: Historical records should persist for audit (payment history)

### 2.3 UniqueConstraints

| Model | Constraint Name | Fields | Purpose |
|-------|-----------------|--------|---------|
| Plan | unique_plan_code_interval | (code, interval) | Prevent duplicate plan codes per billing interval; e.g., "pro" monthly and "pro" yearly are distinct |
| Subscription | unique_plan | (user, plan) | One subscription per user per plan; prevents duplicate subscriptions |

### 2.4 App Separation Strategy (Domain-Driven Design)

| Domain | App | Models | Responsibility |
|--------|-----|--------|----------------|
| Identity | users | User | User authentication, profiles, avatars |
| Conversation | chat | Session, Message, Memory, MemoryBullet | Chat sessions, message history, memory persistence |
| Commerce | billing | Plan, Subscription, Payment | Subscription plans, user subscriptions, payment processing |
| Orchestration | memoria | (none) | URL routing, view wiring, app entry point |

**Rationale**:
- Clear bounded contexts prevent model coupling
- Each app can evolve independently
- Simplifies testing (isolated test suites per domain)
- Aligns with single responsibility principle
- Easier onboarding for new developers

### 2.5 Index Strategy

| Model | Index Fields | Query Pattern Optimized |
|-------|--------------|-------------------------|
| Session | (user, -created_at) | Fetch user's most recent sessions |
| Message | (session, created_at) | Retrieve messages in chronological order |
| Memory | (user, -access_clock) | Decay-based memory retrieval, most active first |
| MemoryBullet | (memory, -last_accessed) | Recent bullet access for relevance scoring |
| Payment | (user, -created_at) | User payment history, most recent first |

### 2.6 Default Ordering

All models define `Meta.ordering` for consistent query results:

| Model | Ordering | Rationale |
|-------|----------|-----------|
| User | ["id"] | Stable ordering by primary key |
| Session | ["-created_at"] | Newest sessions first |
| Message | ["created_at"] | Chronological conversation flow |
| Memory | ["-access_clock"] | Most accessed memories first |
| MemoryBullet | ["-last_accessed"] | Most recently accessed bullets first |
| Plan | ["price_cents"] | Plans ordered by price |
| Subscription | ["-created_at"] | Newest subscriptions first |
| Payment | ["-created_at"] | Most recent payments first |
