"""CNS (schizophrenia / psychosis) trial scenario.

Reference trial: CATIE (Lieberman JA et al., NEJM 2005). n=1,493. 18 months.
Typical Phase 2/3 CNS trial: 200–800 patients, 15–30 sites, 12–24 months.

Population characteristics:
  - Broad health literacy: 12% below basic in general US population (NCES 2003).
  - Caregiver-dependent and low-access archetypes well-represented.
  - High dropout early: median time-to-discontinuation ~6 months (CATIE).
  - Mean age ~40 (CATIE: 40.6 years).

Protocol characteristics:
  - Moderate visit burden: monthly assessments typical for CNS instruments.
  - Moderate protocol complexity (PANSS/BPRS + safety labs).
"""

from __future__ import annotations

import numpy as np

from clinfish.core.engine import SimConfig
from clinfish.domain.agents import PatientPopulationConfig, ArchetypeID, ARCHETYPES


def default(
    n_patients: int = 400,
    n_sites: int = 20,
    n_rounds: int = 18,
    seed: int = 0,
) -> SimConfig:
    """CNS schizophrenia Phase 3 default. Calibrated to CATIE parameters."""
    pop_config = PatientPopulationConfig(
        n_patients=n_patients,
        n_sites=n_sites,
        # Broader prior: CNS populations span education levels.
        belief_prior_alpha=2.5,
        belief_prior_beta=3.5,
        # Mixed literacy: general population distribution (NCES 2003).
        health_literacy_shift=0.0,
        mean_age=40.6,
        # CATIE enrolled broadly: more high-anxiety and low-access vs. trial average.
        archetype_proportions=np.array([
            0.28,   # TREATMENT_NAIVE_HIGH_ANXIETY — elevated in psychosis populations
            0.10,   # EXPERIENCED_ADVOCATE — lower in CNS (stigma barrier)
            0.20,   # CAREGIVER_DEPENDENT_ELDERLY — family caregivers common in geriatric CNS
            0.27,   # LOW_ACCESS_RURAL — rural mental health access barriers
            0.15,   # MOTIVATED_YOUNG_ADULT
        ]),
    )
    return SimConfig(
        therapeutic_area="cns",
        n_patients=n_patients,
        n_sites=n_sites,
        n_rounds=n_rounds,
        months_per_round=1.0,
        # Monthly assessments + safety labs: moderate visit burden.
        protocol_visit_burden=0.55,
        # Moderate protocol complexity: PANSS/BPRS + AIMS + Columbia.
        protocol_burden=0.50,
        monitoring_active=True,
        seed=seed,
        pop_config=pop_config,
    )
