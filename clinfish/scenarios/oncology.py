"""Oncology trial scenario.

Reference: Tufts CSDD oncology late-phase survey 2019. Median n≈300 Phase 2,
n≈700 Phase 3. Median duration ~24 months. Protocol deviations: 46.6% of
patients (Krudys 2022, PMC8979478).

Population characteristics:
  - Higher health literacy than average: oncology patients actively research
    treatments (health literacy shift +0.15 vs. general population).
  - Experienced advocates well-represented: cancer advocacy networks robust.
  - Low-access populations under-represented due to geographic bias of cancer
    centers (Loree JM et al., JAMA Oncology 2019: +10.1% white residents
    vs. national average in trial catchment areas, 95% CI +6.8–+13.7%).
  - High treatment motivation: patients often enroll as last-resort option.
    Beta(1.5, 3.0) → right-skewed toward higher initial willingness.

Protocol characteristics:
  - High visit burden: weekly/biweekly assessments in early cycles.
  - High protocol complexity: mandatory biopsies, RECIST imaging, CTCAE.
  - Amendment rate elevated: 90% of oncology trials require ≥1 amendment
    (vs. 76% overall; Getz 2024, PMID 38438658).
"""

from __future__ import annotations

import numpy as np

from clinfish.core.engine import SimConfig
from clinfish.domain.agents import PatientPopulationConfig


def default(
    n_patients: int = 500,
    n_sites: int = 25,
    n_rounds: int = 24,
    seed: int = 0,
) -> SimConfig:
    """Oncology Phase 3 default. Calibrated to Tufts CSDD 2019 and AACT."""
    pop_config = PatientPopulationConfig(
        n_patients=n_patients,
        n_sites=n_sites,
        # Higher initial willingness: patients often enrolled as last resort.
        # Beta(1.5, 3.0): skewed toward belief > 0.5 (desperate motivation).
        belief_prior_alpha=1.5,
        belief_prior_beta=3.0,
        # Higher literacy: educated patients dominate cancer trial populations.
        health_literacy_shift=0.15,
        mean_age=58.0,
        # Cancer trial population: educated, experienced advocates overrepresented;
        # low-access underrepresented (Loree 2019, JAMA Oncology).
        archetype_proportions=np.array([
            0.20,   # TREATMENT_NAIVE_HIGH_ANXIETY
            0.25,   # EXPERIENCED_ADVOCATE — elevated vs. general trial population
            0.15,   # CAREGIVER_DEPENDENT_ELDERLY
            0.15,   # LOW_ACCESS_RURAL — underrepresented in oncology centers
            0.25,   # MOTIVATED_YOUNG_ADULT
        ]),
    )
    return SimConfig(
        therapeutic_area="oncology",
        n_patients=n_patients,
        n_sites=n_sites,
        n_rounds=n_rounds,
        months_per_round=1.0,
        # High visit burden: weekly labs + imaging cycles.
        protocol_visit_burden=0.70,
        # High protocol complexity: mandatory biopsies, RECIST, CTCAE reporting.
        protocol_burden=0.65,
        monitoring_active=True,
        seed=seed,
        pop_config=pop_config,
    )
