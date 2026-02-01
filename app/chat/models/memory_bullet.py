from django.db import models

class MemoryType(models.IntegerChoices):
    SEMANTIC = 1,
    EPISODIC = 2,
    PROCEDURAL = 3

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

    class Meta:
        indexes = [models.Index(fields=["memory","-last_accessed"])]
        ordering = ["-last_accessed"]
