"""Alzheimer's disease Phase 3 trial scenario.

Reference trials:
  - A4 Study: Donohue MC et al., Alzheimer's & Dementia 2020. n=4,486.
    Preclinical AD; age OR = 1.06 per year for dropout.
  - Phase 3 AD meta-analysis: 21.2% ± 10.8% dropout at 1.4 years
    (7 trials, n=8,103).
  - EMERGE / ENGAGE (aducanumab): ~600 sites globally; 78-week treatment period.

Population characteristics:
  - Oldest mean age: AD Phase 3 typical range 60–85, mean ~72.
  - Caregiver-dependent elderly is the dominant archetype.
  - Caregiver quality is the primary determinant of retention and adherence.
  - Family functioning ↔ adherence: r=0.13–0.18 (Pai & McGrady, PMC7967873).
  - Low health literacy in study participants but caregiver-driven reporting.
  - STAI anxiety OR = 1.07 per unit for dropout (A4 Study, Donohue 2020).

Protocol characteristics:
  - High visit burden: monthly IV infusions + quarterly cognitive batteries
    (ADAS-cog, CDR, MMSE).
  - High procedure burden: lumbar punctures, amyloid PET for eligibility.
  - ARIA monitoring requires frequent MRI (safety stop rules).
"""

from __future__ import annotations

import numpy as np

from clinfish.core.engine import SimConfig
from clinfish.domain.agents import PatientPopulationConfig


def default(
    n_patients: int = 350,
    n_sites: int = 40,
    n_rounds: int = 18,
    seed: int = 0,
) -> SimConfig:
    """AD Phase 3 default. Calibrated to A4 Study and Phase 3 AD meta-analysis."""
    pop_config = PatientPopulationConfig(
        n_patients=n_patients,
        n_sites=n_sites,
        # Moderate initial prior: AD patients motivated (last-resort) but anxious
        # about lumbar punctures and imaging procedures.
        belief_prior_alpha=2.0,
        belief_prior_beta=3.5,
        # Low literacy shift: AD patients rely on caregivers for health info.
        health_literacy_shift=-0.05,
        mean_age=72.0,
        # AD: dominated by elderly with caregiver dependence.
        # A4 Study age distribution informs the elevated elderly proportion.
        archetype_proportions=np.array([
            0.25,   # TREATMENT_NAIVE_HIGH_ANXIETY — STAI anxiety elevated in AD
            0.05,   # EXPERIENCED_ADVOCATE — very rare in frail elderly
            0.45,   # CAREGIVER_DEPENDENT_ELDERLY — dominant in AD trials
            0.15,   # LOW_ACCESS_RURAL — rural AD burden real but limited trial sites
            0.10,   # MOTIVATED_YOUNG_ADULT — young-onset AD; small minority
        ]),
    )
    return SimConfig(
        therapeutic_area="alzheimers",
        n_patients=n_patients,
        n_sites=n_sites,
        n_rounds=n_rounds,
        months_per_round=1.0,
        # High visit burden: monthly infusions + ARIA MRI monitoring.
        protocol_visit_burden=0.72,
        # High complexity: LP, amyloid PET, ADAS-cog, CDR, MMSE, ADCS-ADL.
        protocol_burden=0.68,
        monitoring_active=True,
        seed=seed,
        pop_config=pop_config,
    )
