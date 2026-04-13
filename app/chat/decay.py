"""Memory strength decay math shared by the ORM layer and the ACE runtime."""
import math

SEMANTIC_DECAY_RATE = 0.01
EPISODIC_DECAY_RATE = 0.05
PROCEDURAL_DECAY_RATE = 0.002


def component_score(strength, last_index, decay_rate, access_clock):
    if strength is None:
        return 0.0
    try:
        strengthFloat = float(strength)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(strengthFloat) or strengthFloat <= 0:
        return 0.0
    base = max(0.0, min(1.0, 1.0 - decay_rate))
    effectiveIndex = last_index if last_index is not None else access_clock
    t = max(access_clock - effectiveIndex, 0)
    return strengthFloat * math.pow(base, t)


def total_strength(
    semantic_strength, semantic_access_index,
    episodic_strength, episodic_access_index,
    procedural_strength, procedural_access_index,
    access_clock,
):
    return (
        component_score(semantic_strength, semantic_access_index, SEMANTIC_DECAY_RATE, access_clock)
        + component_score(episodic_strength, episodic_access_index, EPISODIC_DECAY_RATE, access_clock)
        + component_score(procedural_strength, procedural_access_index, PROCEDURAL_DECAY_RATE, access_clock)
    )
