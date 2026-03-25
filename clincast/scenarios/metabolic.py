"""Metabolic / T2DM trial scenario.

Reference: AACT database T2DM/metabolic subset. ~31% overall dropout.
Typical Phase 3 T2DM trial: 300–1,000 patients, 30–80 sites, 24–52 weeks.

Population characteristics:
  - Older adult population (mean ~55–60).
  - High comorbidity burden: obesity, hypertension, CKD.
  - MEMS cross-study mean adherence 74.9% (Vrijens & Urquhart 2005 SR).
  - Antihypertensive proxy (Vrijens 2008): 65% persistence at day 200.
  - T2DM-specific MEMS data limited; antihypertensive treated as directional.

Protocol characteristics:
  - Lower visit burden than oncology: monthly → quarterly schedule.
  - HbA1c, FPG, insulin as primary endpoints — relatively low procedure burden.
  - Oral agent trials: adherence challenges from side-effect (GI) profile.
"""

from __future__ import annotations

import numpy as np

from clincast.core.engine import SimConfig
from clincast.domain.agents import PatientPopulationConfig


def default(
    n_patients: int = 450,
    n_sites: int = 35,
    n_rounds: int = 24,
    seed: int = 0,
) -> SimConfig:
    """Metabolic/T2DM Phase 3 default. Calibrated to AACT database."""
    pop_config = PatientPopulationConfig(
        n_patients=n_patients,
        n_sites=n_sites,
        # Moderate prior: established SOC for T2DM; stable initial trust.
        belief_prior_alpha=3.0,
        belief_prior_beta=2.5,
        # Mixed literacy: T2DM spans socioeconomic strata.
        health_literacy_shift=0.03,
        mean_age=57.0,
        # T2DM: older, lower access (rural T2DM burden is high).
        archetype_proportions=np.array([
            0.22,   # TREATMENT_NAIVE_HIGH_ANXIETY
            0.12,   # EXPERIENCED_ADVOCATE
            0.24,   # CAREGIVER_DEPENDENT_ELDERLY — insulin-dependent elderly
            0.28,   # LOW_ACCESS_RURAL — rural T2DM burden elevated
            0.14,   # MOTIVATED_YOUNG_ADULT
        ]),
    )
    return SimConfig(
        therapeutic_area="metabolic",
        n_patients=n_patients,
        n_sites=n_sites,
        n_rounds=n_rounds,
        months_per_round=1.0,
        # Quarterly visits + HbA1c: low-to-moderate visit burden.
        protocol_visit_burden=0.40,
        # Moderate complexity: CGM, HbA1c, FPG, insulin titration.
        protocol_burden=0.42,
        monitoring_active=True,
        seed=seed,
        pop_config=pop_config,
    )
