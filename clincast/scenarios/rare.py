"""Rare disease trial scenario.

Reference: Tufts CSDD 2019 rare disease survey. Late-phase orphan trials:
  - Typical n=30–150 (small due to prevalence cap).
  - 6.5% cumulative dropout at 24 months [GROUNDED — Tufts 2019].
    λ back-calculated: λ = -24 / ln(1 - 0.065) = 356 months.
  - High patient motivation: no or few alternatives; advocacy networks strong.
  - Sites specialized: most trials at academic centers of excellence (ACoEs).
    ACoE site activation often < 90 days (targets met more often than general).

Population characteristics:
  - Highly motivated: ultra-low dropout reflects desperation and community cohesion.
  - Strong patient advocacy networks: rare disease patient organizations are
    among the best-organized in clinical trial support (NORD data).
  - Health literacy elevated: patients and caregivers become disease experts.
  - Age varies: some rare diseases are pediatric (proxy adult population here);
    metabolic rare diseases often present in young adults.

Protocol characteristics:
  - High complexity: novel endpoints, mandatory genetic confirmation,
    specialized imaging (MRI, PET, optical coherence tomography).
  - High visit burden: frequent longitudinal biomarker assessments.
  - Small N means every patient matters: high monitoring intensity.
"""

from __future__ import annotations

import numpy as np

from clincast.core.engine import SimConfig
from clincast.domain.agents import PatientPopulationConfig


def default(
    n_patients: int = 80,
    n_sites: int = 8,
    n_rounds: int = 24,
    seed: int = 0,
) -> SimConfig:
    """Rare disease Phase 3 default. Calibrated to Tufts CSDD 2019."""
    pop_config = PatientPopulationConfig(
        n_patients=n_patients,
        n_sites=n_sites,
        # Strong initial motivation: rare disease patients have few alternatives.
        belief_prior_alpha=1.5,
        belief_prior_beta=5.0,
        # Elevated literacy: rare disease patients and caregivers are expert-patients.
        health_literacy_shift=0.20,
        mean_age=38.0,
        # Rare disease: highly motivated, advocacy-connected, educated.
        archetype_proportions=np.array([
            0.10,   # TREATMENT_NAIVE_HIGH_ANXIETY — exists but managed by advocacy
            0.30,   # EXPERIENCED_ADVOCATE — elevated: advocacy networks prominent
            0.20,   # CAREGIVER_DEPENDENT_ELDERLY — pediatric and adult forms
            0.05,   # LOW_ACCESS_RURAL — travel to ACoE often funded by advocacy orgs
            0.35,   # MOTIVATED_YOUNG_ADULT — dominant in rare disease trials
        ]),
    )
    return SimConfig(
        therapeutic_area="rare",
        n_patients=n_patients,
        n_sites=n_sites,
        n_rounds=n_rounds,
        months_per_round=1.0,
        # High visit burden: specialized assessments, frequent biomarkers.
        protocol_visit_burden=0.65,
        # High complexity: genetic confirmation, novel endpoints, mandatory biopsies.
        protocol_burden=0.60,
        monitoring_active=True,
        seed=seed,
        pop_config=pop_config,
    )
