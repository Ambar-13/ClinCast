"""Vectorized patient population — numpy float32 arrays.

All N patients are represented as parallel arrays rather than Python objects.
This gives ~100-1000x speedup over per-agent Python loops at population sizes
relevant to clinical trials (500-5000 patients).

State per patient (one float32 per column):
  belief          Current health belief / trust in trial (0-1).
                  Initialized from therapeutic-area priors; updated each round
                  via DeGroot averaging on the patient social network.
  adherence_prob  Round-level probability of being adherent this round.
                  Computed from clinical_response.adherence() each round.
  dropout_hazard  Instantaneous hazard of dropping out this round.
                  Sum of cause-specific hazards (AE, LTFU, withdrawal, etc.)
  cumulative_ae   Accumulated adverse event load (0-1 scale).
                  Feeds back into dropout_hazard each round.
  visit_burden    Protocol visit burden experienced by this patient.
                  Function of site_access_score and protocol_intensity.
  status          0 = screening, 1 = enrolled, 2 = dropout, 3 = completed.
                  Population conservation: inflows to 1 equal outflows from 0;
                  outflows from 1 go to 2 or 3.

Design follows the Bank of England housing market ABM (Baptista et al., 2016)
and the IIASA macroeconomic ABM (Dosi et al., 2010) in using rule-based
heterogeneous agents for population dynamics while reserving LLM deliberation
for the small persona-agent swarm layer.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from clincast.domain.agents import PatientPopulationConfig, ARCHETYPES, ArchetypeID


# Column indices — kept as named constants so array access is readable
COL_BELIEF          = 0
COL_ADHERENCE_PROB  = 1
COL_DROPOUT_HAZARD  = 2
COL_CUMULATIVE_AE   = 3
COL_VISIT_BURDEN    = 4
COL_STATUS          = 5
COL_INSTITUTIONAL_TRUST = 6   # slow-updating sponsor trust (information stock)
COL_TRIAL_FATIGUE       = 7   # accumulating fatigue stock (inflow: visits+AEs, outflow: recovery)
COL_CONSCIENTIOUSNESS   = 8   # Big Five Conscientiousness trait [GROUNDED: Roberts 2009 meta r=0.19]
COL_PERSONAL_CONTROL    = 9   # IPQ-R Personal Control subscale [GROUNDED: Hagger & Orbell 2003]
COL_ADHERENCE_STATE     = 10  # Markov adherence state: 0=holiday, 1=taking [GROUNDED: Vrijens 2008]
N_COLS = 11

# Status codes
STATUS_SCREENING  = 0.0
STATUS_ENROLLED   = 1.0
STATUS_DROPOUT    = 2.0
STATUS_COMPLETED  = 3.0


@dataclasses.dataclass
class PopulationArray:
    """Float32 array of shape (n_patients, N_COLS) plus metadata arrays."""

    state: np.ndarray               # (n, N_COLS) float32 — main state
    archetype_ids: np.ndarray       # (n,) int8 — index into archetype registry
    site_ids: np.ndarray            # (n,) int16 — which site this patient is at
    health_literacy: np.ndarray     # (n,) float32 — fixed covariate, 0-1
    site_access_score: np.ndarray   # (n,) float32 — distance-decay, 0-1
    age: np.ndarray                 # (n,) float32 — years
    rng: np.random.Generator

    @classmethod
    def generate(
        cls,
        config: PatientPopulationConfig,
        seed: int = 0,
    ) -> "PopulationArray":
        """Draw a heterogeneous patient population from the config distributions.

        Covariates are drawn once at initialization and held fixed throughout
        the simulation. This matches the clinical trial assumption that patient
        demographics are observed at enrollment and don't change.
        """
        rng = np.random.default_rng(seed)
        n = config.n_patients

        state = np.zeros((n, N_COLS), dtype=np.float32)
        state[:, COL_STATUS] = STATUS_SCREENING

        # Initial beliefs drawn from per-TA prior distribution
        state[:, COL_BELIEF] = rng.beta(
            config.belief_prior_alpha,
            config.belief_prior_beta,
            size=n,
        ).astype(np.float32)

        # Archetype assignment — draw from configured proportions
        archetype_ids = rng.choice(
            len(config.archetype_proportions),
            size=n,
            p=config.archetype_proportions,
        ).astype(np.int8)

        # Site assignment — uniform across sites initially; can be reweighted
        site_ids = rng.integers(0, config.n_sites, size=n).astype(np.int16)

        # Health literacy: Beta(2, 2) centred at 0.5, reflecting general population.
        # Shift mean upward for trials with educated recruitment strategies.
        health_literacy = rng.beta(2.0, 2.0, size=n).astype(np.float32)
        health_literacy = np.clip(
            health_literacy + config.health_literacy_shift, 0.0, 1.0
        )

        # Site access score: captures geographic distance and transport.
        # Gamma(2, 0.5) rescaled to [0,1]; shape matches observed right-skew
        # in travel-time distributions (longer tails for rural patients).
        raw_access = rng.gamma(2.0, 0.5, size=n)
        site_access_score = (raw_access / raw_access.max()).astype(np.float32)

        # Age: normal centred at config.mean_age with SD 12, clipped to [18, 90]
        age = rng.normal(config.mean_age, 12.0, size=n).astype(np.float32)
        age = np.clip(age, 18.0, 90.0)

        # Initial institutional trust drawn from same prior as belief (can diverge later)
        state[:, COL_INSTITUTIONAL_TRUST] = state[:, COL_BELIEF].copy()

        # Trial fatigue starts at 0 (builds during trial)
        state[:, COL_TRIAL_FATIGUE] = 0.0

        # Conscientiousness: Beta(2.5, 2.5) centered at 0.5, slight positive skew for trial enrollees
        # Roberts et al. (2009) meta-analysis: Conscientiousness r=0.19 with adherence
        # [GROUNDED direction; Beta parameterization ASSUMED]
        state[:, COL_CONSCIENTIOUSNESS] = rng.beta(2.5, 2.5, size=n).astype(np.float32)

        # Personal Control (IPQ-R): Beta(3, 2) mean=0.6 — trial enrollees self-select for agency
        # Hagger & Orbell (2003) meta: IPQ-R personal control r=0.21 with coping/adherence
        # [GROUNDED direction; prior ASSUMED]
        state[:, COL_PERSONAL_CONTROL] = rng.beta(3.0, 2.0, size=n).astype(np.float32)

        # Initial adherence state: Bernoulli(archetype_adherence_prob) for each patient
        # Vrijens et al. BMJ 2008: ~50% in non-persistence by 1 year but execution rate ~90%
        # Initialize most patients as "taking" (adherence_state=1)
        adherence_init_probs = np.array([ARCHETYPES[ArchetypeID(i)].baseline_adherence for i in range(len(ArchetypeID))])
        patient_adherence_probs = adherence_init_probs[archetype_ids.astype(np.int8)]
        state[:, COL_ADHERENCE_STATE] = rng.random(n).astype(np.float32) < patient_adherence_probs

        return cls(
            state=state,
            archetype_ids=archetype_ids,
            site_ids=site_ids,
            health_literacy=health_literacy,
            site_access_score=site_access_score,
            age=age,
            rng=rng,
        )

    @property
    def n(self) -> int:
        return self.state.shape[0]

    def enrolled(self) -> np.ndarray:
        """Boolean mask of currently enrolled patients."""
        return self.state[:, COL_STATUS] == STATUS_ENROLLED

    def screening(self) -> np.ndarray:
        return self.state[:, COL_STATUS] == STATUS_SCREENING

    def beliefs(self) -> np.ndarray:
        return self.state[:, COL_BELIEF]

    def set_beliefs(self, new_beliefs: np.ndarray) -> None:
        self.state[:, COL_BELIEF] = new_beliefs.astype(np.float32)

    def enroll(self, mask: np.ndarray) -> None:
        """Move patients from screening to enrolled. Preserves conservation."""
        self.state[mask & self.screening(), COL_STATUS] = STATUS_ENROLLED

    def drop_out(self, mask: np.ndarray) -> None:
        self.state[mask & self.enrolled(), COL_STATUS] = STATUS_DROPOUT

    def complete(self, mask: np.ndarray) -> None:
        self.state[mask & self.enrolled(), COL_STATUS] = STATUS_COMPLETED

    def accumulate_ae(self, delta: np.ndarray) -> None:
        """Add adverse event load; clamp to [0, 1]."""
        self.state[:, COL_CUMULATIVE_AE] = np.clip(
            self.state[:, COL_CUMULATIVE_AE] + delta, 0.0, 1.0
        ).astype(np.float32)

    def summary(self) -> dict[str, float]:
        enrolled_mask = self.enrolled()
        n_enrolled = int(enrolled_mask.sum())
        return {
            "n_screening": int(self.screening().sum()),
            "n_enrolled": n_enrolled,
            "n_dropout": int((self.state[:, COL_STATUS] == STATUS_DROPOUT).sum()),
            "n_completed": int((self.state[:, COL_STATUS] == STATUS_COMPLETED).sum()),
            "mean_belief_enrolled": float(
                self.state[enrolled_mask, COL_BELIEF].mean()
            ) if n_enrolled > 0 else 0.0,
            "mean_adherence_prob": float(
                self.state[enrolled_mask, COL_ADHERENCE_PROB].mean()
            ) if n_enrolled > 0 else 0.0,
            "mean_ae_load": float(
                self.state[enrolled_mask, COL_CUMULATIVE_AE].mean()
            ) if n_enrolled > 0 else 0.0,
        }
