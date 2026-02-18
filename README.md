# MEMORIA: A Self-Evolving Agentic Framework with Transparent, User-Controlled Memory

**Memory Enhanced Multi-modal Orchestration Reasoning Intelligence Architecture**

**By Team MIRA (Team 4)**

Memory Incremental Reasoning Architecture

---

## Abstract

We present Memory Enhanced Multi-modal Orchestration Reasoning Intelligence Architecture (MEMORIA), a web application that enables self-evolving AI assistants with transparent, user-controlled memory. Our system addresses fundamental inefficiencies in current AI interactions, where users constantly have to re-establish context across sessions, resulting in significant token waste and degraded performance. MEMORIA learns user work patterns through procedural learning rather than extensive conversation history, achieving personalization comparable to fine-tuning at approximately 1% of the token cost. Users can visualize, rate, and modify the AI's learned memory, creating unprecedented transparency in personalized AI systems.

---

## Introduction

Large language models have demonstrated remarkable capabilities across diverse tasks, yet they face a fundamental architectural limitation: the absence of persistent, adaptive memory that accumulates knowledge from user interactions over time. Each new conversation session requires users to re-explain their preferences, context, and working style, creating substantial friction in human-AI collaboration. Research demonstrates that LLMs suffer a 39% performance drop in multi-turn conversations as they fail to maintain coherent context over extended interactions.

---

## Key Features

MEMORIA provides four core capabilities that distinguish it from traditional LLM interfaces:

### 1. Transparent Memory Interface
Users maintain complete visibility and control over all stored memories. The system exposes memory contents, relevance scores, and decay states through an intuitive interface, enabling users to inspect, modify, or delete any stored information.

### 2. Procedural Learning Engine
Beyond storing facts, MEMORIA captures procedural knowledge including user preferences, interaction patterns, and task-specific instructions. The system learns how users prefer to accomplish tasks, not just what they know.

### 3. Efficient Memory Retrieval
The LTMBSE-ACE algorithm combines Bloom filter indexing with strength-based scoring to retrieve relevant memories in sublinear time. This enables responsive performance even as memory stores grow large.

### 4. Feedback Integration
User feedback directly influences memory strength and relevance. Positive reinforcement strengthens useful memories while negative signals accelerate decay of unhelpful content, creating a continuously improving system.

---

## Application Functionality

MEMORIA supports three primary operations that enable adaptive, personalized assistance:

### Memory Extraction
The system continuously analyzes conversations to identify and extract memorable content. Facts, preferences, procedures, and episodic experiences are taxonomized and stored with appropriate decay rates based on memory type.

### Context Augmentation
When generating responses, MEMORIA retrieves relevant memories and augments the context without requiring user re-specification. This eliminates redundant information exchange while maintaining natural conversation flow.

### Feedback Integration
Users can rate the helpfulness of retrieved memories, providing direct feedback that adjusts memory strength scores. This creates a reinforcement loop that continuously improves retrieval relevance.

---

## Installation

1. Clone the repository:
```bash
git clone https://github.com/Edward-H26/MIRA.git
cd MIRA
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp .env.example .env
```

Then edit `.env` and replace `YOUR_KEY` with a freshly generated Django secret key:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

5. Run migrations:
```bash
python manage.py migrate
```

6. Start the development server:
```bash
python manage.py runserver
```

---

## Project Structure

```
.
|-- manage.py                     # Django management script
|-- requirements.txt              # Python dependencies
|-- .env.example                  # Environment variable template
|
|-- app/                          # Application modules
|   |-- billing/                  # Billing and subscription domain (scaffolded)
|   |   `-- models: Plan, Subscription, Payment
|   |
|   |-- chat/                     # Chat sessions, messages, memory
|   |   |-- models: Memory, MemoryBullet, Session, Message
|   |   |-- views.py              # MemoryListView, ConversationMessagesView, MemoryBulletsView, analytics, charts, rename/delete
|   |   |-- urls.py               # /chat/memory/, /chat/c/<id>/, /chat/m/<id>/, analytics, API routes (15 patterns)
|   |   |-- api.py                # JSON API views (memories, analytics, sessions, messages, demo)
|   |   |-- service.py            # 22 service functions (sessions, memory, analytics, charts, API payloads)
|   |   |-- context_processors.py # user_sessions (injects sidebar session list)
|   |   |-- templatetags/         # chat_extras: relative_time filter
|   |   |-- templates/chat/       # conversation_detail.html, memory.html, analytics.html
|   |   `-- static/chat/          # analytics.css, chat.css, conversation.css, memory.css
|   |
|   |-- memoria/                  # Main app wiring (landing, home, 404)
|   |   |-- views.py              # home(), landing(), not_found_view()
|   |   |-- urls.py               # /, /home/
|   |   |-- templates/memoria/    # home.html, landing.html
|   |   `-- static/memoria/       # home.css, landing.css, landing-overrides.css
|   |
|   `-- users/                    # Authentication and user profiles
|       |-- models.py             # User (profile with profile_img)
|       |-- views.py              # login, register, logout, profile, password change
|       |-- urls.py               # /users/login/, /users/register/, /users/profile/, etc.
|       |-- services.py           # authenticate_and_login, register_and_login, create_user_with_profile
|       |-- middleware.py         # Custom middleware
|       |-- templates/users/      # login_form, register_form, profile, password_change_form
|       `-- static/users/         # auth-modal.css, profile.css
|
|-- memoria/                      # Project configuration
|   |-- settings/                 # Environment-specific settings
|   |   |-- base.py               # Shared settings (apps, middleware, templates, db)
|   |   |-- development.py        # Dev overrides (DEBUG, ALLOWED_HOSTS)
|   |   `-- production.py         # Prod overrides
|   |-- templates/memoria/        # landing.html (standalone, project-level)
|   |-- urls.py                   # Root URL conf (includes app URLs + handler404)
|   |-- asgi.py
|   `-- wsgi.py
|
|-- templates/                    # Project-level templates
|   `-- base.html                 # Global base template (sidebar, navbar, content blocks)
|
|-- static/                       # Project-level static assets
|   |-- css/
|   |   |-- base.css              # Global layout, sidebar, navbar styles
|   |   `-- main.css              # Compiled/additional styles
|   |-- js/
|   |   `-- main.js               # Sidebar toggle, AJAX handlers, UI interactions
|   `-- images/                   # Logo, avatar, icons, background images
|
|-- docs/                         # Project documentation
|   |-- 01_project_documents/     # Idea description PDF, contribution report
|   |-- 02_wireframes/            # UI wireframes v1, v2, v3 iterations + final PDF
|   |-- 03_data_model/            # ER diagrams (Mermaid source, PNG, SVG)
|   |-- 04_branching_strategy/    # Git branching documentation
|   |-- 05_notes/                 # Weekly progress notes
|   |-- imgs/                     # Screenshot evidence for assignment sections
|   `-- design_choice/            # database_design_choice.md
|
|-- data/                         # Local data storage
`-- unit_test/                    # Test suite
    |-- mock_data.py              # Shared test data (8 users + admin, 5 plans, 26 bullets, 17 sessions, 49 messages)
    |-- database_unit_test.py     # Database relationship and constraint tests
    `-- feature_unit_test.py      # Service layer and API payload tests
```

---

## Data Model

![ER Diagram](docs/03_data_model/er_diagram.png)

---

## Team

**Authors:**

- **Qiran Hu** (First Author, Algorithm Originator)
- **Amy Bisalputra** (Equal Contribution, Application Development)
- **Ke Ding** (Equal Contribution, Application Development)
- **Min Kim** (Equal Contribution, Application Development)
- **Kewen Xia** (Equal Contribution, Application Development)

---

## Acknowledgements

The LTMBSE-ACE algorithm implemented in MEMORIA derives from foundational work on the NOODEIA project conducted at SALT Lab. We thank the INFO 490 course for providing the framework and guidance that enabled this research contribution.

---

## UI and Styling

MEMORIA features a polished, production-grade interface built with vanilla CSS and no frontend build tools. The design uses frosted glass effects (`backdrop-filter: blur`), gradient backgrounds with layered radial gradients, the Inter typeface for clean typography, and custom SVG icons throughout. A collapsible sidebar modeled after ChatGPT, Claude, and Gemini provides 5 navigation items: Home, Memory, Analytics, New Chat, and Search. Static files use a hybrid organization with project-level shared assets and app-level feature-specific styles. Cache busting in development appends Unix timestamps via `{% now 'U' %}`.

Screenshots:

![Home Dashboard](docs/imgs/home_dashboard_normal.png)
![Memory Management](docs/imgs/memory_management_normal.png)
![Conversation Detail](docs/imgs/conversation_detail_normal.png)
![Sidebar Collapsed](docs/imgs/sidebar_collapsed.png)

---

## URL Note

The root URL (`/`) resolves to the landing page, and authenticated workflow continues through `/home/`, `/chat/memory/`, `/chat/c/<session_id>/`, and `/chat/m/<memory_id>/`.  
Detail navigation uses model-driven URLs via `get_absolute_url()` on `Session` and `Memory`, so templates link objects directly without hard-coded paths.  
This keeps URL routing maintainable and ensures list-to-detail navigation stays consistent across sidebar conversations, memory cards, and API payloads.

---

## Analytics Dashboard

The analytics page at `/chat/analytics/` displays three server-side charts generated with Matplotlib:

1. **Memory Type Distribution** (Pie): Balance of Semantic, Episodic, and Procedural memories
2. **Memory Strength Distribution** (Bar): Count of memories across strength ranges
3. **Conversation Activity** (Line): Sessions created per day over the last 30 days

Each chart is served as a standalone PNG image at its own URL endpoint (e.g., `/chat/analytics/memory-type.png`).

---

## API Endpoints

MEMORIA exposes JSON APIs for internal frontend use and future client integration:

Detailed API documentation:
- [API Overview](docs/06_api/api_overview.md)

| Endpoint | Method | Description | Filters |
|---|---|---|---|
| `/chat/api/memories/` | GET | Memory bullets | `?q=`, `?type=`, `?topic=`, `?strength_min=` |
| `/chat/api/analytics/` | GET | Aggregated analytics summary | None |
| `/chat/api/sessions/` | GET | User sessions | `?q=` |
| `/chat/api/sessions/<id>/messages/` | GET | Messages for a session | `?role=` |

The sessions API powers the sidebar search modal (Ctrl+K).

---

## Week 4 Features

Features added in Week 4:
- **Sidebar navigation** with 5 items (Home, Memory, Analytics, New Chat, Search)
- **Conversation search modal** triggered by Ctrl+K / Cmd+K
- **Conversation rename and delete** with backend persistence
- **Memory detail page** at `/chat/m/<id>/` showing all bullets for a memory record
- **POST search** on home page for private conversation content search
- **ORM aggregations** (Count, grouped Count, Avg, Max, Min, Sum) displayed in stat cards
- **Analytics dashboard** with 3 Matplotlib charts using BytesIO
- **MemoryListView** (ListView CBV) handling both GET and POST
- **4 JSON API endpoints** (2 FBV, 2 CBV)

---

## Testing

MEMORIA includes a comprehensive test suite covering database integrity, service layer functions, API payloads, and chart generation.

### Test Files

| File | Purpose | Tests |
|---|---|---|
| `unit_test/mock_data.py` | Shared test data module | 8 test users + admin seeding, 5 plans, 26 memory bullets, 12 sessions + 5 admin sessions, 36 + 13 messages |
| `unit_test/database_unit_test.py` | Database relationships and constraints | FK chains, uniqueness, on_delete (CASCADE, PROTECT, SET_NULL), model methods |
| `unit_test/feature_unit_test.py` | Service layer and API testing | 67 tests across 8 groups (users, sessions, memory, analytics, charts, API, models, edge cases) |

### Running Tests

All test and data scripts must be run from the **project root**:

```bash
# Seed the database with mock data
python unit_test/mock_data.py

# Run tests
python unit_test/database_unit_test.py          # Run all database tests
python unit_test/feature_unit_test.py           # Run all feature tests
python unit_test/feature_unit_test.py --test-api    # Run API payload tests only
python unit_test/feature_unit_test.py --test-charts # Run chart generation tests only
```

### Mock Data Coverage

The shared mock data module provides realistic test personas covering power users, free tier users, edge cases (empty data, max-length fields, special characters), and deletion targets. Memory bullet strengths span all 5 histogram buckets (0-20, 21-40, 41-60, 61-80, 81-100), and all 3 MemoryType values (Semantic, Episodic, Procedural) are distributed across users. Subscription and payment records cover all status enums (ACTIVE, EXPIRED, INCOMPLETE, SUCCEEDED, FAILED, PENDING, CANCELLED).

In addition to the 8 test users, the script seeds demo data for the existing admin account (`tester`). This includes 5 sessions (backdated across different days), 13 messages, 1 memory record, and 5 memory bullets so the admin user sees realistic content in the sidebar, memory page, and analytics charts immediately after seeding. All sessions (both test user and admin) are backdated to different days within the last 30 days to produce a realistic Conversation Activity chart, with at least one day containing 2 sessions.

---

## Week 5 Features

Features added in Week 5:
- **Comprehensive test infrastructure** with shared mock data module
- **Database unit tests** expanded with model method validation, extended uniqueness checks, and failure counter with exit codes
- **Feature unit tests** covering all 20 service functions, 5 user service functions, 4 API payload builders, and 3 chart generators
- **Edge case testing** for empty users, boundary values, and non-numeric filter parameters

---

## Development

This project uses Django 6.0.1. For development setup, ensure you have Python 3.12+ installed.

---

## License

This project is developed for INFO 490.
