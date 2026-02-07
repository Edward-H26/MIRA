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
|   |   |-- views.py              # chat_view, memory_view, ConversationMessagesView, MemoryBulletsView
|   |   |-- urls.py               # /chat/, /chat/memory/, /chat/c/<id>/, /chat/m/<id>/
|   |   |-- service.py            # create_user_message_with_agent_reply()
|   |   |-- context_processors.py # user_sessions (injects sidebar session list)
|   |   |-- templatetags/         # chat_extras: relative_time filter
|   |   |-- templates/chat/       # conversation_detail.html, memory.html
|   |   `-- static/chat/          # chat.css, conversation.css, memory.css
|   |
|   |-- memoria/                  # Main app wiring (landing, home, 404)
|   |   |-- views.py              # home(), landing(), not_found_view()
|   |   |-- urls.py               # /, /home/
|   |   |-- templates/memoria/    # home.html, landing.html
|   |   `-- static/memoria/       # landing.css, landing-overrides.css
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
|   `-- design_choice/            # database_design_choice.md
|
|-- data/                         # Local data storage
`-- unit_test/                    # Test suite
    `-- database_unit_test.py     # Database unit tests
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

## Development

This project uses Django 6.0.1. For development setup, ensure you have Python 3.12+ installed.

---

## License

This project is developed for INFO 490.
