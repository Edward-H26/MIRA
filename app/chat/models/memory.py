from django.db import models
from django.urls import reverse
import math
import random

class Memory(models.Model):
    """
    Real-world entity: Memory record attached to a user
    Why it exists: Persist long-term memory items for personalization
    """
    # The user this memory belongs to; cascade to avoid orphaned memories
    user = models.ForeignKey("users.UserProfile", on_delete=models.CASCADE)
    # Number of access events processed since the component was last retrieved
    access_clock = models.IntegerField(default=0)
    # Planner policy snapshot for ACE action selection (epsilon/UCB stats)
    planner_state = models.JSONField(default=dict, blank=True)
    # Timestamp when the memory record was created
    created_at = models.DateTimeField(auto_now_add=True)
    # Timestamp when the memory record was last updated
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['updated_at']
        indexes = [models.Index(fields=['user','-access_clock'])]

    def __str__(self):
        return f"{self.user_id} - {self.id}"

    def get_absolute_url(self):
        return reverse("chat:memory_detail", kwargs={"memory_id": self.pk})

    @classmethod
    def get_or_create_for_profile(cls, profile):
        existing = cls.objects.filter(user=profile).order_by("-updated_at", "-id").first()
        if existing is not None:
            return existing, False
        created = cls.objects.create(user=profile, access_clock=0, planner_state={})
        return created, True

    def ensure_seed_bullets(self, learner_id, seed_texts):
        from .memory_bullet import MemoryBullet
        if MemoryBullet.objects.filter(memory=self).exists():
            return
        for text in seed_texts:
            MemoryBullet.create_seed(memory=self, learner_id=learner_id, content=text)

    def choose_planner_action(self, feature_text, actions, epsilon, ucb_c, seed):
        planner_state = dict(self.planner_state or {})
        action_stats = planner_state.get("actions", {})
        total_pulls = int(planner_state.get("total_pulls", 0))
        rng = random.Random(int(seed) + self.access_clock + len(feature_text or ""))

        for action in actions:
            action_stats.setdefault(action, {"pulls": 0, "updates": 0, "reward_sum": 0.0})

        explore = rng.random() < float(epsilon)
        scores = {}
        for action, stats in action_stats.items():
            pulls = int(stats.get("pulls", 0))
            updates = int(stats.get("updates", 0))
            reward_sum = float(stats.get("reward_sum", 0.0))
            mean = reward_sum / updates if updates > 0 else 0.5
            bonus = float(ucb_c) * math.sqrt(math.log(total_pulls + len(action_stats) + 1) / (pulls + 1))
            scores[action] = mean + bonus

        if explore:
            action_id = rng.choice(list(actions))
        else:
            action_id = sorted(scores.keys(), key=lambda key: (scores[key], key), reverse=True)[0]

        action_stats[action_id]["pulls"] = int(action_stats[action_id].get("pulls", 0)) + 1
        planner_state["actions"] = action_stats
        planner_state["total_pulls"] = total_pulls + 1
        self.planner_state = planner_state
        self.save(update_fields=["planner_state"])
        return action_id

    def update_planner_reward(self, action_id, reward, confidence):
        planner_state = dict(self.planner_state or {})
        action_stats = planner_state.get("actions", {})
        stats = dict(action_stats.get(action_id, {"pulls": 0, "updates": 0, "reward_sum": 0.0}))
        clipped_reward = max(0.0, min(1.0, float(reward)))
        clipped_conf = max(0.0, min(1.0, float(confidence)))
        weighted_reward = clipped_reward * clipped_conf
        stats["updates"] = int(stats.get("updates", 0)) + 1
        stats["reward_sum"] = float(stats.get("reward_sum", 0.0)) + weighted_reward
        action_stats[action_id] = stats
        planner_state["actions"] = action_stats
        planner_state["total_updates"] = int(planner_state.get("total_updates", 0)) + 1
        self.planner_state = planner_state
        self.save(update_fields=["planner_state"])

    def retrieve_ranked_bullets(
        self,
        query,
        learner_id,
        context_scope_id,
        top_k,
        min_learned,
        base_strength,
        relevance_w,
        strength_w,
        type_w,
        seed_penalty,
        learned_bonus,
    ):
        from .memory_bullet import MemoryBullet
        from django.utils import timezone

        bullets = list(
            MemoryBullet.objects.filter(memory=self, learner_id=learner_id)
            .filter(context_scope_id__in=["", context_scope_id])
            .order_by("-last_accessed")
        )

        scored = []
        for bullet in bullets:
            strength_score = MemoryBullet.compute_strength_score(bullet, self.access_clock)
            relevance = MemoryBullet.text_similarity(query, bullet.content)
            type_priority = MemoryBullet.memory_type_priority(bullet.memory_type)
            tags = {tag.lower() for tag in (bullet.tags or [])}
            bonus = float(learned_bonus) if "meta_strategy" not in tags else -float(seed_penalty)
            combined = (
                float(relevance_w) * relevance
                + float(strength_w) * (strength_score / max(float(base_strength), 1.0))
                + float(type_w) * type_priority
                + bonus
            )
            scored.append((combined, bullet))
        scored.sort(key=lambda row: row[0], reverse=True)

        selected = []
        selected_ids = set()
        for _, bullet in scored:
            if "meta_strategy" in {tag.lower() for tag in (bullet.tags or [])}:
                continue
            selected.append(bullet)
            selected_ids.add(bullet.id)
            if len(selected) >= min(min_learned, top_k):
                break
        for _, bullet in scored:
            if bullet.id in selected_ids:
                continue
            selected.append(bullet)
            if len(selected) >= top_k:
                break

        if selected:
            self.access_clock += 1
            now = timezone.now()
            access_index = self.access_clock
            for bullet in selected:
                MemoryBullet.touch_channel(
                    bullet=bullet,
                    channel=MemoryBullet.memory_type_to_channel(bullet.memory_type),
                    access_index=access_index,
                    now=now,
                )
            MemoryBullet.objects.bulk_update(
                selected,
                [
                    "last_accessed",
                    "semantic_access_index",
                    "episodic_access_index",
                    "procedural_access_index",
                    "semantic_last_access",
                    "episodic_last_access",
                    "procedural_last_access",
                ],
            )
            self.save(update_fields=["access_clock"])

        return selected

    def apply_lessons(self, lessons, learner_id, context_scope_id):
        from .memory_bullet import MemoryBullet
        from django.utils import timezone
        import hashlib

        now = timezone.now()
        updated_count = 0
        created_count = 0

        for lesson in lessons:
            content = (lesson.get("content") or "").strip()
            if not content:
                continue
            content_hash = MemoryBullet.compute_content_hash(content)
            match = MemoryBullet.objects.filter(memory=self, content_hash=content_hash).first()
            if not match:
                for bullet in MemoryBullet.objects.filter(memory=self, learner_id=learner_id)[:120]:
                    if MemoryBullet.text_similarity(content, bullet.content) >= 0.9:
                        match = bullet
                        break

            if match:
                match.helpful_count += 1
                channel = MemoryBullet.memory_type_to_channel(match.memory_type)
                self.access_clock += 1
                MemoryBullet.touch_channel(match, channel, self.access_clock, now)
                if channel == "episodic":
                    match.episodic_strength = max(match.episodic_strength, 100.0)
                elif channel == "procedural":
                    match.procedural_strength = max(match.procedural_strength, 100.0)
                else:
                    match.semantic_strength = max(match.semantic_strength, 100.0)
                match.save(update_fields=[
                    "helpful_count",
                    "last_accessed",
                    "semantic_access_index",
                    "episodic_access_index",
                    "procedural_access_index",
                    "semantic_last_access",
                    "episodic_last_access",
                    "procedural_last_access",
                    "semantic_strength",
                    "episodic_strength",
                    "procedural_strength",
                ])
                updated_count += 1
                continue

            memory_type = MemoryBullet.infer_memory_type(content)
            channel = MemoryBullet.memory_type_to_channel(memory_type)
            self.access_clock += 1
            access_index = self.access_clock
            new_bullet = MemoryBullet(
                memory=self,
                content=content,
                tags=lesson.get("tags") or ["lesson"],
                helpful_count=1,
                harmful_count=0,
                memory_type=memory_type,
                topic=(lesson.get("tags") or ["general"])[0],
                strength=100,
                ttl_days=365,
                concept=None,
                bullet_key=hashlib.md5(content.lower().encode()).hexdigest()[:12],
                context_scope_id=context_scope_id,
                learner_id=learner_id,
                content_hash=content_hash,
            )
            if channel == "episodic":
                new_bullet.episodic_strength = 100.0
                new_bullet.episodic_access_index = access_index
                new_bullet.episodic_last_access = now
            elif channel == "procedural":
                new_bullet.procedural_strength = 100.0
                new_bullet.procedural_access_index = access_index
                new_bullet.procedural_last_access = now
            else:
                new_bullet.semantic_strength = 100.0
                new_bullet.semantic_access_index = access_index
                new_bullet.semantic_last_access = now
            new_bullet.save()
            created_count += 1

        self.save(update_fields=["access_clock"])

        try:
            from app.services.neo4j_memory import sync_memory_to_neo4j
            sync_memory_to_neo4j(learner_id, self)
        except Exception:
            pass

        return {"num_new_bullets": created_count, "num_updates": updated_count, "num_removals": 0}
