import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone

from app.users.models import UserProfile
from app.chat.models.session import Session
from app.chat.models.message import Message, Role
from app.chat.models.memory import Memory
from app.chat.models.memory_bullet import MemoryBullet, MemoryType
from app.chat.models.request_log import RequestLog


MODEL_WEIGHTS = [
    ("gemini-3-flash-preview", 0.70),
    ("gemini-3.1-flash-lite-preview", 0.15),
    ("qwen3.5-0.8b", 0.15),
]
MODEL_NAMES = [m[0] for m in MODEL_WEIGHTS]
MODEL_CUM_WEIGHTS = [w for _, w in MODEL_WEIGHTS]

REQUEST_TYPE_WEIGHTS = [
    ("chat", 0.75),
    ("classify", 0.15),
    ("structured", 0.10),
]
REQUEST_TYPES = [r[0] for r in REQUEST_TYPE_WEIGHTS]
REQUEST_CUM_WEIGHTS = [w for _, w in REQUEST_TYPE_WEIGHTS]

STATUS_WEIGHTS = [
    ("success", 0.92),
    ("fallback", 0.05),
    ("error", 0.03),
]
STATUSES = [s[0] for s in STATUS_WEIGHTS]
STATUS_CUM_WEIGHTS = [w for _, w in STATUS_WEIGHTS]

ERROR_TYPES = ["TimeoutError", "APIError", "RateLimitError"]

COST_TABLE = {
    "gemini-3-flash-preview": {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},
    "gemini-3.1-flash-lite-preview": {"input": 0.075 / 1_000_000, "output": 0.30 / 1_000_000},
    "qwen3.5-0.8b": {"input": 0.0, "output": 0.0},
}

SESSION_TITLES = [
    "Chat about Python",
    "Help with homework",
    "Explain machine learning",
    "Debug JavaScript code",
    "Study for midterm",
    "Review lecture notes",
    "Practice SQL queries",
    "Discuss data structures",
    "Plan research project",
    "Explore NLP concepts",
    "Write lab report",
    "Prepare presentation slides",
    "Understand recursion",
    "Compare sorting algorithms",
    "Learn about APIs",
    "Work on group project",
    "Analyze dataset",
    "Brainstorm essay topics",
    "Solve math problems",
    "Review exam material",
    "Discuss ethics in AI",
    "Build a web app",
    "Docker setup help",
    "Git workflow questions",
    "Career advice chat",
]

USER_MESSAGES = [
    "Can you explain this concept to me?",
    "I'm stuck on this problem, can you help?",
    "What's the difference between these two approaches?",
    "How do I implement this in Python?",
    "Can you review my code?",
    "I don't understand this error message.",
    "What are the best practices for this?",
    "Can you give me an example?",
]

ASSISTANT_MESSAGES = [
    "Sure, let me break that down for you.",
    "Great question! Here's how I'd approach it.",
    "Let me walk you through the steps.",
    "Here's an example that should help clarify things.",
    "The key concept here is that the algorithm works by...",
    "I'd recommend starting with the basics and building up.",
    "Looking at your code, I can see the issue is...",
    "There are several ways to handle this, but the most common is...",
]

MEMORY_BULLETS_DATA = [
    ("User prefers Python for coding tasks", "episodic", "programming"),
    ("The quadratic formula solves ax^2 + bx + c = 0", "semantic", "math"),
    ("Step 1: import the library, Step 2: load data, Step 3: preprocess", "procedural", "data_science"),
    ("User asked about recursion multiple times", "episodic", "programming"),
    ("Big-O notation describes algorithmic complexity", "semantic", "algorithms"),
    ("User prefers concise explanations", "episodic", "preferences"),
    ("REST APIs use HTTP methods for CRUD operations", "semantic", "web_development"),
    ("Step 1: git add, Step 2: git commit, Step 3: git push", "procedural", "version_control"),
    ("User has experience with JavaScript", "episodic", "programming"),
    ("Neural networks consist of layers of connected nodes", "semantic", "machine_learning"),
    ("User struggles with SQL joins", "episodic", "databases"),
    ("Step 1: define schema, Step 2: create migration, Step 3: apply", "procedural", "databases"),
    ("Binary search requires a sorted array", "semantic", "algorithms"),
    ("User is taking an intro to CS course", "episodic", "education"),
    ("Merge sort has O(n log n) time complexity", "semantic", "algorithms"),
    ("Step 1: write test, Step 2: implement feature, Step 3: refactor", "procedural", "testing"),
    ("User prefers dark mode in IDE", "episodic", "preferences"),
    ("HTTP status 404 means resource not found", "semantic", "web_development"),
    ("Step 1: create venv, Step 2: install deps, Step 3: activate", "procedural", "python_setup"),
    ("User has a deadline next Friday", "episodic", "scheduling"),
    ("Linked lists provide O(1) insertion at head", "semantic", "data_structures"),
    ("User mentioned interest in AI research", "episodic", "career"),
    ("Gradient descent minimizes a loss function iteratively", "semantic", "machine_learning"),
    ("Step 1: fork repo, Step 2: clone, Step 3: create branch, Step 4: PR", "procedural", "collaboration"),
    ("User asked about Docker containers vs VMs", "episodic", "devops"),
    ("CAP theorem states you can only guarantee two of three properties", "semantic", "distributed_systems"),
    ("Step 1: gather requirements, Step 2: design, Step 3: implement, Step 4: test", "procedural", "software_engineering"),
    ("User enjoys working on data visualization projects", "episodic", "interests"),
    ("Hash maps provide average O(1) lookup time", "semantic", "data_structures"),
    ("Step 1: define model, Step 2: train, Step 3: evaluate, Step 4: deploy", "procedural", "ml_workflow"),
    ("User needs help with LaTeX formatting", "episodic", "tools"),
    ("Normalization reduces data redundancy in databases", "semantic", "databases"),
    ("User is comfortable with Linux command line", "episodic", "skills"),
    ("Polymorphism allows objects of different classes to be treated uniformly", "semantic", "oop"),
    ("Step 1: read paper, Step 2: summarize, Step 3: critique, Step 4: present", "procedural", "research"),
    ("User prefers examples over theory", "episodic", "learning_style"),
    ("TCP ensures reliable ordered delivery of packets", "semantic", "networking"),
    ("User is working on a group project with 3 teammates", "episodic", "collaboration"),
    ("Dijkstra's algorithm finds shortest paths from a single source", "semantic", "algorithms"),
    ("Step 1: collect data, Step 2: clean, Step 3: explore, Step 4: model", "procedural", "data_analysis"),
]

MEMORY_TYPE_MAP = {
    "semantic": MemoryType.SEMANTIC,
    "episodic": MemoryType.EPISODIC,
    "procedural": MemoryType.PROCEDURAL,
}


def _pick_weighted(values, weights):
    return random.choices(values, weights=weights, k=1)[0]


def _generate_latency(request_type):
    if request_type == "chat":
        raw = random.gauss(700, 250)
        return max(200, min(1500, int(raw)))
    elif request_type == "classify":
        raw = random.gauss(180, 80)
        return max(50, min(400, int(raw)))
    else:
        raw = random.gauss(900, 350)
        return max(300, min(2000, int(raw)))


def _generate_tokens(latency_ms):
    latency_factor = latency_ms / 1000.0
    prompt = int(random.uniform(100, 2000) * (0.5 + 0.5 * latency_factor))
    prompt = max(100, min(2000, prompt))
    completion = int(random.uniform(50, 1500) * (0.3 + 0.7 * latency_factor))
    completion = max(50, min(1500, completion))
    return prompt, completion


def _hour_weight(hour):
    if 9 <= hour <= 22:
        return 3.0
    elif 7 <= hour <= 8 or hour == 23:
        return 1.5
    else:
        return 0.3


class Command(BaseCommand):
    help = "Seed realistic analytics data for dashboard demo"

    def add_arguments(self, parser):
        parser.add_argument("--user", default="mohitg2", type=str)
        parser.add_argument("--days", default=90, type=int)

    def handle(self, *args, **options):
        username = options["user"]
        days = options["days"]

        profile = self._ensure_user_and_profile(username)
        sessions = self._seed_sessions(profile, days)
        self._seed_messages(sessions)
        self._seed_memory_bullets(profile)
        self._seed_request_logs(profile, sessions, days)

        self.stdout.write(self.style.SUCCESS("Analytics seed data created successfully."))

    def _ensure_user_and_profile(self, username):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": f"{username}@example.com"},
        )
        if created:
            user.set_password("uiuc12345")
            user.is_staff = True
            user.is_superuser = True
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Created user: {username}"))
        else:
            changed = False
            if not user.is_staff:
                user.is_staff = True
                changed = True
            if not user.is_superuser:
                user.is_superuser = True
                changed = True
            if changed:
                user.save()
            self.stdout.write(self.style.NOTICE(f"User already exists: {username}"))

        profile, p_created = UserProfile.objects.get_or_create(
            user=user,
            defaults={"display_name": username},
        )
        if p_created:
            self.stdout.write(self.style.SUCCESS(f"Created UserProfile for: {username}"))

        return profile

    def _seed_sessions(self, profile, days):
        num_sessions = random.randint(15, 25)
        now = timezone.now()
        start = now - timedelta(days=days)
        sessions = []

        titles = random.sample(SESSION_TITLES, min(num_sessions, len(SESSION_TITLES)))
        for i in range(num_sessions):
            offset_seconds = random.randint(0, days * 86400)
            created_at = start + timedelta(seconds=offset_seconds)
            title = titles[i] if i < len(titles) else f"Session {i + 1}"
            session = Session(
                user=profile,
                title=title,
            )
            session._seed_created_at = created_at
            sessions.append(session)

        Session.objects.bulk_create(sessions)

        for session in sessions:
            Session.objects.filter(pk=session.pk).update(
                created_at=session._seed_created_at,
                updated_at=session._seed_created_at + timedelta(minutes=random.randint(5, 120)),
            )

        sessions = list(Session.objects.filter(pk__in=[s.pk for s in sessions]).order_by("created_at"))
        self.stdout.write(self.style.SUCCESS(f"Created {len(sessions)} sessions"))
        return sessions

    def _seed_messages(self, sessions):
        messages = []
        for session in sessions:
            num_pairs = random.randint(3, 8)
            base_time = session.created_at
            for j in range(num_pairs):
                msg_time = base_time + timedelta(seconds=30 * (2 * j))
                messages.append(Message(
                    session=session,
                    role=Role.USER,
                    content=random.choice(USER_MESSAGES),
                ))
                messages.append(Message(
                    session=session,
                    role=Role.ASSISTANT,
                    content=random.choice(ASSISTANT_MESSAGES),
                ))

        Message.objects.bulk_create(messages)
        self.stdout.write(self.style.SUCCESS(f"Created {len(messages)} messages"))

    def _seed_memory_bullets(self, profile):
        memory, _ = Memory.get_or_create_for_profile(profile)
        num_bullets = random.randint(20, 40)
        selected = random.sample(
            MEMORY_BULLETS_DATA,
            min(num_bullets, len(MEMORY_BULLETS_DATA)),
        )

        bullets = []
        for content, type_str, topic in selected:
            bullets.append(MemoryBullet(
                memory=memory,
                content=content,
                memory_type=MEMORY_TYPE_MAP[type_str],
                strength=random.randint(30, 95),
                topic=topic,
                tags=[topic],
            ))

        MemoryBullet.objects.bulk_create(bullets)
        self.stdout.write(self.style.SUCCESS(f"Created {len(bullets)} memory bullets"))

    def _seed_request_logs(self, profile, sessions, days):
        RequestLog.objects.filter(metadata__seeded=True).delete()

        now = timezone.now()
        start = now - timedelta(days=days)
        total_rows = random.randint(700, 2000)

        hours = list(range(24))
        hour_weights = [_hour_weight(h) for h in hours]

        logs = []
        for _ in range(total_rows):
            day_offset = random.randint(0, days - 1)
            hour = _pick_weighted(hours, hour_weights)
            minute = random.randint(0, 59)
            second = random.randint(0, 59)
            created_at = start + timedelta(days=day_offset, hours=hour, minutes=minute, seconds=second)

            model_name = _pick_weighted(MODEL_NAMES, MODEL_CUM_WEIGHTS)
            request_type = _pick_weighted(REQUEST_TYPES, REQUEST_CUM_WEIGHTS)
            status = _pick_weighted(STATUSES, STATUS_CUM_WEIGHTS)

            if status == "fallback":
                pipeline = "fallback"
            elif "qwen" in model_name:
                pipeline = "local_qwen"
            else:
                pipeline = "gemini_direct"

            latency_ms = _generate_latency(request_type)
            prompt_tokens, completion_tokens = _generate_tokens(latency_ms)
            total_tokens = prompt_tokens + completion_tokens

            rates = COST_TABLE[model_name]
            estimated_cost_usd = (
                prompt_tokens * rates["input"] + completion_tokens * rates["output"]
            )

            error_type = ""
            if status == "error":
                error_type = random.choice(ERROR_TYPES)

            session = random.choice(sessions) if random.random() < 0.8 else None

            logs.append(RequestLog(
                user=profile,
                session=session,
                request_type=request_type,
                model_name=model_name,
                pipeline=pipeline,
                status=status,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=estimated_cost_usd,
                error_type=error_type,
                metadata={"seeded": True},
            ))

        RequestLog.objects.bulk_create(logs)

        pk_time_pairs = []
        for log in logs:
            day_offset = random.randint(0, days - 1)
            hour = _pick_weighted(hours, hour_weights)
            minute = random.randint(0, 59)
            second = random.randint(0, 59)
            target_time = start + timedelta(days=day_offset, hours=hour, minutes=minute, seconds=second)
            pk_time_pairs.append((log.pk, target_time))

        for pk, target_time in pk_time_pairs:
            RequestLog.objects.filter(pk=pk).update(created_at=target_time)

        self.stdout.write(self.style.SUCCESS(f"Created {len(logs)} request log entries over {days} days"))
