from django.db import models
from django.utils import timezone
import hashlib
import math
import re

class MemoryType(models.IntegerChoices):
    SEMANTIC = 1, "Semantic"
    EPISODIC = 2, "Episodic"
    PROCEDURAL = 3, "Procedural"

class MemoryBullet(models.Model):
    """
    Real-world entity: Granular memory item for a memory
    Why it exists: Store individual memory facts with metadata and scoring
    """
    # Parent memory record this bullet belongs to; cascade to keep bullets in sync with the parent
    memory = models.ForeignKey("Memory", on_delete=models.CASCADE)
    # The memory content text
    content = models.TextField()
    # The tag of memory summarized
    tags = models.JSONField(default=list)
    # Count of helpful votes
    helpful_count = models.IntegerField(default=0)
    # Count of harmful votes
    harmful_count = models.IntegerField(default=0)
    # Type or category of this memory item
    memory_type = models.SmallIntegerField(choices=MemoryType)
    # Topic label for the memory item
    topic = models.CharField(max_length=200)
    # Timestamp when the memory bullet was created
    created_at = models.DateTimeField(auto_now_add=True)
    # Strength of memory decay rate
    strength = models.IntegerField(default=0)
    # Timestamp of last access or update
    last_accessed = models.DateTimeField(auto_now=True)
    # Concept of the memory
    concept = models.TextField(null=True)
    # Days of time before deletion
    ttl_days = models.IntegerField()
    # ACE stable bullet identifier for dedup and delta update mapping
    bullet_key = models.CharField(max_length=32, blank=True, default="", db_index=True)
    # Scoped retrieval dimension to avoid cross-session contamination
    context_scope_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    # Learner identity for retrieval isolation
    learner_id = models.CharField(max_length=120, blank=True, default="", db_index=True)
    # Normalized content hash for exact dedup lookup
    content_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    # ACE tri-memory strengths
    semantic_strength = models.FloatField(default=0.0)
    episodic_strength = models.FloatField(default=0.0)
    procedural_strength = models.FloatField(default=0.0)
    # Per-channel access clocks
    semantic_access_index = models.IntegerField(null=True, blank=True)
    episodic_access_index = models.IntegerField(null=True, blank=True)
    procedural_access_index = models.IntegerField(null=True, blank=True)
    # Per-channel access timestamps
    semantic_last_access = models.DateTimeField(null=True, blank=True)
    episodic_last_access = models.DateTimeField(null=True, blank=True)
    procedural_last_access = models.DateTimeField(null=True, blank=True)
    is_skill = models.BooleanField(default=False, db_index=True)
    skill_enabled = models.BooleanField(default=True)
    skill_group = models.CharField(max_length=100, blank=True, default="")
    embedding_json = models.TextField(blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["memory","-last_accessed"])]
        ordering = ["-last_accessed"]

    TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

    @staticmethod
    def tokenize(text):
        return MemoryBullet.TOKEN_PATTERN.findall((text or "").lower())

    @staticmethod
    def text_similarity(a, b):
        wa = set(MemoryBullet.tokenize(a))
        wb = set(MemoryBullet.tokenize(b))
        if not wa or not wb:
            return 0.0
        return len(wa.intersection(wb)) / len(wa.union(wb))

    @staticmethod
    def compute_content_hash(text):
        normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
        return hashlib.sha256(normalized.encode()).hexdigest()

    @staticmethod
    def memory_type_to_channel(memory_type):
        if memory_type == MemoryType.EPISODIC:
            return "episodic"
        if memory_type == MemoryType.PROCEDURAL:
            return "procedural"
        return "semantic"

    @staticmethod
    def memory_type_priority(memory_type):
        if memory_type == MemoryType.PROCEDURAL:
            return 1.0
        if memory_type == MemoryType.EPISODIC:
            return 0.7
        return 0.4

    @staticmethod
    def infer_memory_type(content):
        lower = (content or "").lower()
        if any(word in lower for word in ["step", "procedure", "workflow", "then", "finally"]):
            return MemoryType.PROCEDURAL
        if any(word in lower for word in ["user", "prefers", "asked", "history", "experience"]):
            return MemoryType.EPISODIC
        return MemoryType.SEMANTIC

    @staticmethod
    def component_score(strength, last_index, decay_rate, access_clock):
        if strength <= 0:
            return 0.0
        base = max(0.0, min(1.0, 1.0 - decay_rate))
        t = max(access_clock - (last_index or access_clock), 0)
        return strength * math.pow(base, t)

    @staticmethod
    def compute_strength_score(bullet, access_clock):
        return (
            MemoryBullet.component_score(bullet.semantic_strength, bullet.semantic_access_index, 0.01, access_clock)
            + MemoryBullet.component_score(bullet.episodic_strength, bullet.episodic_access_index, 0.05, access_clock)
            + MemoryBullet.component_score(bullet.procedural_strength, bullet.procedural_access_index, 0.002, access_clock)
        )

    @staticmethod
    def touch_channel(bullet, channel, access_index, now):
        bullet.last_accessed = now
        if channel == "episodic":
            bullet.episodic_access_index = access_index
            bullet.episodic_last_access = now
        elif channel == "procedural":
            bullet.procedural_access_index = access_index
            bullet.procedural_last_access = now
        else:
            bullet.semantic_access_index = access_index
            bullet.semantic_last_access = now

    @classmethod
    def create_seed(cls, memory, learner_id, content):
        return cls.objects.create(
            memory=memory,
            content=content,
            tags=["meta_strategy", "procedural"],
            helpful_count=5,
            harmful_count=0,
            memory_type=MemoryType.PROCEDURAL,
            topic="meta_strategy",
            strength=100,
            ttl_days=3650,
            concept="meta_strategy",
            learner_id=learner_id,
            content_hash=cls.compute_content_hash(content),
            bullet_key=hashlib.md5(content.lower().encode()).hexdigest()[:12],
            procedural_strength=100.0,
            procedural_access_index=memory.access_clock,
            procedural_last_access=timezone.now(),
        )
