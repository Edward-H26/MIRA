# MEMORIA: A Self-Evolving Agentic Framework with Transparent, User-Controlled Memory

**By Team MIRA (Team 4)**

Memory Incremental Reasoning Architecture

---

## Abstract

Large Language Models demonstrate remarkable capabilities across diverse tasks, yet their stateless architecture creates fundamental inefficiencies when users repeatedly provide contextual information across sessions. This context inefficiency problem results in wasted tokens, degraded user experience, and missed opportunities for personalized assistance. MEMORIA addresses these challenges through a self-evolving agentic framework that maintains persistent, transparent user memory while preserving complete user control. Our system implements a Latent Taxonomized Memory with Bloom-filter enabled Strength-based Extraction and Adaptive Cohort Expansion algorithm that extracts, taxonomizes, and retrieves relevant memories with minimal overhead. Through transparent memory interfaces, users can inspect, modify, and control all stored information. Experimental results demonstrate that MEMORIA achieves 95% reduction in redundant context tokens compared to traditional approaches while maintaining response quality, at approximately 1% of the cost of fine-tuning solutions. The framework's combination of efficiency, transparency, and user control offers a practical path toward truly personalized AI assistants that learn and adapt while respecting user agency.

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
|-- manage.py              # Django management script
|-- app/                   # Application modules
|   |-- billing/           # Billing and subscription domain
|   |   `-- models: Plan, Subscription, Payment
|   |-- chat/              # Chat sessions, messages, memory
|   |   `-- models: Memory, MemoryBullet, Session, Message
|   |-- memoria/           # App wiring (urls, views)
|   |   `-- models: (none)
|   `-- users/             # User profile models
|       `-- models: User
|-- mira/                  # Project configuration
|   |-- settings/
|   |-- asgi.py
|   |-- urls.py
|   `-- wsgi.py
|-- data/                  # Local data storage
|-- media/                 # User-uploaded files
|-- requirements.txt       # Python dependencies
|-- .env                   # Local environment variables
`-- .env.example           # Environment template
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
