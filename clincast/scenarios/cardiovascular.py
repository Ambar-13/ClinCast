"""Cardiovascular trial scenario.

Reference trials:
  - CHARM Overall: Granger CB et al., Lancet 2003. n=7,599. ≥2 years.
  - MERIT-HF: n=3,991. ~1 year mean follow-up.
  - ATLAS ACS 2-TIMI 51: ~9% withdrawal of consent per arm at 13.1 months.

Large Phase 3 CV trials: median n~3,000–8,000, 40–100+ sites, 24–60 months.
Default uses a scaled-down version (500 patients, 30 sites) for tractable
simulation, with per-patient parameters calibrated to large-trial moments.

Population characteristics:
  - Older mean age: CHARM mean age ~65.
  - Comorbidities increase caregiver dependence; elderly archetype elevated.
  - Moderate health literacy: heart failure population is broad.
  - Antihypertensive adherence proxy: Vrijens 2008 (BMJ, PMC2386633),
    65% persistence at day 200.
"""

from __future__ import annotations

import numpy as np

from clincast.core.engine import SimConfig
from clincast.domain.agents import PatientPopulationConfig


def default(
    n_patients: int = 600,
    n_sites: int = 30,
    n_rounds: int = 36,
    seed: int = 0,
) -> SimConfig:
    """CV Phase 3 default. Calibrated to CHARM Overall and MERIT-HF."""
    pop_config = PatientPopulationConfig(
        n_patients=n_patients,
        n_sites=n_sites,
        # Moderate priors: established treatment landscape, moderate trust.
        belief_prior_alpha=3.0,
        belief_prior_beta=3.0,
        # General population health literacy: CV is a broad disease.
        health_literacy_shift=0.05,
        mean_age=65.0,
        # HF trial: older, more comorbid → more caregiver-dependent.
        archetype_proportions=np.array([
            0.18,   # TREATMENT_NAIVE_HIGH_ANXIETY
            0.12,   # EXPERIENCED_ADVOCATE
            0.32,   # CAREGIVER_DEPENDENT_ELDERLY — elevated for HF population
            0.22,   # LOW_ACCESS_RURAL — rural CV disease burden is high
            0.16,   # MOTIVATED_YOUNG_ADULT
        ]),
    )
    return SimConfig(
        therapeutic_area="cardiovascular",
        n_patients=n_patients,
        n_sites=n_sites,
        n_rounds=n_rounds,
        months_per_round=1.0,
        # Quarterly clinic visits + remote monitoring: moderate burden.
        protocol_visit_burden=0.45,
        # Moderate complexity: ECG, echo, labs, KCCQ, 6MWT.
        protocol_burden=0.45,
        monitoring_active=True,
        seed=seed,
        pop_config=pop_config,
    )
