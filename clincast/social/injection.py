"""Adversarial belief injection — push a belief into a patient subpopulation mid-trial.

Use cases:
  - Misinformation spread: a false safety claim circulates in patient forums
    at a given round. Measure how far it propagates and how much it increases
    dropout hazard.
  - Positive campaign: a patient advocacy group publishes endorsement. Measure
    enrollment uplift.
  - Protocol amendment leak: rumour of an upcoming protocol change (dose
    reduction, additional visits) reaches patients before the official
    announcement. Measure anticipatory dropout.

Injection mechanics follow the influence cascade literature (Dodds & Watts,
2004, American Journal of Sociology): a fraction of the population is seeded
with a new belief, and DeGroot propagation on the patient network carries it
forward. The fraction that adopt the injected belief by round T gives the
cascade reach.

The injected belief competes with the patient's current belief via a weighted
average controlled by susceptibility, which itself is a function of health
literacy and cumulative AE load (stressed patients are more susceptible to
negative misinformation — consistent with Betsch et al., 2011, Health Psychology).
"""

from __future__ import annotations

import dataclasses
from enum import Enum

import numpy as np


class InjectionValence(str, Enum):
    NEGATIVE = "negative"   # misinformation, safety scare, protocol rumour
    POSITIVE = "positive"   # advocacy endorsement, peer success story


@dataclasses.dataclass
class InjectionEvent:
    """A single belief injection event."""

    round_index: int             # simulation round when injection fires
    target_belief: float         # belief value pushed into seed patients (0-1)
    seed_fraction: float         # fraction of enrolled patients directly seeded
    valence: InjectionValence
    label: str                   # human-readable description for the evidence pack

    # Optional: restrict injection to specific archetypes or sites.
    # None = inject across the full enrolled population.
    target_archetype_ids: list[int] | None = None
    target_site_ids: list[int] | None = None


@dataclasses.dataclass
class InjectionResult:
    """Outcome of one injection event, measured across subsequent rounds."""

    event: InjectionEvent
    round_seeded: int
    n_seeded: int
    belief_at_injection: float    # mean belief of seeded patients before injection
    cascade_reach_by_round: list[float]  # fraction of enrolled pop with belief > threshold
    dropout_delta_by_round: list[float]  # excess dropout vs. counterfactual (ASSUMED)


def apply_injection(
    pop_beliefs: np.ndarray,
    pop_ae_load: np.ndarray,
    health_literacy: np.ndarray,
    enrolled_mask: np.ndarray,
    archetype_ids: np.ndarray,
    site_ids: np.ndarray,
    event: InjectionEvent,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply one injection event to the population belief array.

    Returns:
        updated_beliefs: np.ndarray — beliefs after injection (same shape)
        seeded_mask: np.ndarray bool — which patients were directly seeded
    """
    # Build eligible pool
    eligible = enrolled_mask.copy()
    if event.target_archetype_ids is not None:
        eligible &= np.isin(archetype_ids, event.target_archetype_ids)
    if event.target_site_ids is not None:
        eligible &= np.isin(site_ids, event.target_site_ids)

    eligible_idx = np.where(eligible)[0]
    if len(eligible_idx) == 0:
        return pop_beliefs.copy(), np.zeros(len(pop_beliefs), dtype=bool)

    n_seed = max(1, int(event.seed_fraction * len(eligible_idx)))
    seeded_idx = rng.choice(eligible_idx, size=n_seed, replace=False)
    seeded_mask = np.zeros(len(pop_beliefs), dtype=bool)
    seeded_mask[seeded_idx] = True

    # Susceptibility to the injected belief.
    # Stressed patients (high AE load) are more susceptible to negative signals;
    # high health literacy patients resist both positive and negative injections more.
    # Betsch et al. (2011) Health Psychology: anxiety moderates health information
    # processing; higher anxiety → stronger negative belief updating.
    ae_susceptibility = 0.3 + 0.5 * pop_ae_load     # [0.3, 0.8] range
    literacy_resistance = 0.2 * health_literacy       # [0, 0.2] damping factor

    if event.valence == InjectionValence.NEGATIVE:
        susceptibility = np.clip(ae_susceptibility - literacy_resistance, 0.1, 0.9)
    else:
        # Positive injections are resisted more uniformly — patients are
        # appropriately sceptical of overly positive claims.
        susceptibility = np.clip(
            0.4 - 0.2 * health_literacy + 0.1 * pop_ae_load, 0.1, 0.6
        )

    updated = pop_beliefs.copy()
    for idx in seeded_idx:
        s = float(susceptibility[idx])
        updated[idx] = (1.0 - s) * pop_beliefs[idx] + s * event.target_belief

    return np.clip(updated, 0.0, 1.0).astype(np.float32), seeded_mask


def measure_cascade(
    beliefs_before: np.ndarray,
    beliefs_after: np.ndarray,
    enrolled_mask: np.ndarray,
    seeded_mask: np.ndarray,
    target_belief: float,
    threshold: float = 0.1,
) -> dict[str, float]:
    """Measure how far the injected belief propagated beyond the seed patients.

    A non-seeded patient has "adopted" the injection if their belief moved
    more than `threshold` toward target_belief compared to beliefs_before.
    """
    non_seeded_enrolled = enrolled_mask & ~seeded_mask
    if non_seeded_enrolled.sum() == 0:
        return {"cascade_reach": 0.0, "mean_belief_delta": 0.0}

    delta = (beliefs_after - beliefs_before) * np.sign(
        target_belief - beliefs_before
    )
    adopted = (delta > threshold) & non_seeded_enrolled
    cascade_reach = float(adopted.sum()) / float(non_seeded_enrolled.sum())
    mean_delta = float(delta[non_seeded_enrolled].mean())

    return {
        "cascade_reach": cascade_reach,
        "mean_belief_delta": mean_delta,
    }
