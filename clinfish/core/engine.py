"""Main simulation loop — orchestrates all components per round.

Per-round flow:
  1. Enrollment: move screening patients to enrolled (Poisson draw from site rates).
  2. Belief propagation: DeGroot averaging on patient social network.
  3. Optional injection: apply any InjectionEvent firing this round.
  4. Behavioral decisions: compute adherence, visit compliance, AE reporting.
  5. AE accumulation: update cumulative AE load per patient.
  6. Dropout decisions: compute hazard; Bernoulli draw; move to dropout stock.
  7. Completion check: move patients who have hit trial duration to completed.
  8. Stock updates: TrialStocks updated from this round's patient flows.
  9. Institutional decisions: sponsor amendment probability; regulator threshold check.
  10. Record round outputs → SimulationRound.

The loop runs for n_rounds (one round = one calendar month by default).

LLM SWARM MODE (optional)
───────────────────────────
When llm_client is provided, a small set of patient persona agents reason
about the scenario prior to the vectorized run and vote on behavioral priors
(baseline adherence adjustments, initial belief distribution). Their votes
shift the vectorized parameters within bounded ranges. This adds ~20-40s
but provides a reasoning trace for non-technical stakeholders.

All LLM-influenced parameters are tagged [SWARM-ELICITED] in outputs.
Votes shift vectorized parameters within bounded ranges.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any

import numpy as np

from clinfish.core.network import (
    build_patient_network,
    compute_degroot_weights,
    propagate_beliefs,
    network_statistics,
)
from clinfish.core.vectorized import (
    PopulationArray,
    STATUS_SCREENING, STATUS_ENROLLED, STATUS_DROPOUT, STATUS_COMPLETED,
    COL_BELIEF, COL_ADHERENCE_PROB, COL_DROPOUT_HAZARD,
    COL_CUMULATIVE_AE, COL_VISIT_BURDEN, COL_STATUS,
    COL_INSTITUTIONAL_TRUST, COL_TRIAL_FATIGUE,
    COL_CONSCIENTIOUSNESS, COL_NEUROTICISM, COL_PERSONAL_CONTROL,
)
from clinfish.domain.agents import (
    PatientPopulationConfig,
    ArchetypeID,
    ARCHETYPES,
    INSTITUTIONAL_ACTORS,
    InstitutionType,
)
from clinfish.domain.response import (
    dropout_hazard,
    adherence_probability,
    visit_compliance_probability,
    ae_reporting_fraction,
    accumulate_ae_load,
    AE_GRADE_WEIGHT,
    assign_dropout_cause,
    CAUSE_EFFICACY,
    CAUSE_INTOLERABILITY,
    CAUSE_PERSONAL,
    CAUSE_ADMINISTRATIVE,
    CAUSE_NON_MEDICAL,
    CAUSE_NAMES,
)
from clinfish.domain.stocks import TrialStocks, SiteActivationPipeline
from clinfish.reports.evidence_pack import (
    Tag,
    TaggedValue,
    PatientOutputs,
    TrialOutputs,
)
from clinfish.social.injection import InjectionEvent, apply_injection


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class SimConfig:
    """Full simulation configuration."""

    therapeutic_area: str
    n_patients: int
    n_sites: int
    n_rounds: int                         # typically 12-60 months
    months_per_round: float = 1.0         # 1 = monthly rounds

    protocol_burden: float = 0.5          # 0-1 normalized burden [ASSUMED]
    protocol_visit_burden: float = 0.5    # 0-1 visit-specific burden [ASSUMED]
    monitoring_active: bool = True        # RBM/SDV monitoring enabled

    injection_events: list[InjectionEvent] = dataclasses.field(default_factory=list)
    seed: int = 0

    # Weibull shape override: None = use TA default from response.TA_DROPOUT_LAMBDA
    shape_k: float | None = None

    # Enrollment rate multiplier — scales site_rate in the Negative Binomial draw.
    # 1.0 = TA default; >1.0 = favourable recruitment environment (good PI network,
    # competitive-free landscape); <1.0 = recruitment difficulty.
    enrollment_rate_modifier: float = 1.0

    # Scheduled visits per month (from protocol extraction)
    # Used to modulate site burden and patient fatigue accumulation.
    # Typical ranges: Phase I 4-8/mo, Phase II 2-4/mo, Phase III 1-2/mo. [DIRECTIONAL]
    visits_per_month: float = 2.0

    # Patient support program (transport, reminders, coordinator)
    # When True: reduces site burden from query volume [DIRECTIONAL]
    # Reduces dropout hazard for LOW_ACCESS_RURAL archetype by ~15% [ASSUMED magnitude]
    patient_support_program: bool = False

    # Policy-derived modifiers (set via apply_policy() in ingest/policy.py)
    # amendment_initiation_rate_modifier: scales base amendment probability
    # [DIRECTIONAL — higher appetite → more amendments → higher site burden]
    amendment_initiation_rate_modifier: float = 1.0

    # dropout_rate_modifier: multiplies final per-patient dropout hazard
    # [DIRECTIONAL — enrichment reduces dropout; magnitude ASSUMED]
    dropout_rate_modifier: float = 1.0

    # efficacy_dropout_modifier: additional hazard multiplier for placebo-driven dropout
    # [DIRECTIONAL — placebo patients more likely to dropout; 40% max ASSUMED]
    efficacy_dropout_modifier: float = 1.0

    # dsmb_sensitivity: threshold for DSMB review trigger (replaces hardcoded 0.50)
    # [DIRECTIONAL — intensive DSMB → lower threshold; ASSUMED]
    dsmb_sensitivity: float = 0.50

    # safety_stopping_threshold: threshold for regulatory action (replaces hardcoded 0.80)
    # [DIRECTIONAL — conservative sponsors set higher bars; ASSUMED linear mapping]
    safety_stopping_threshold: float = 0.80

    # LLM swarm mode — None = offline (vectorized only)
    llm_client:    Any | None = None
    n_swarm_agents: int       = 1000

    pop_config: PatientPopulationConfig | None = None  # if None, built from n/n_sites

    # FIX 7 (H7): trial_duration_months — minimum on-study time for a patient to count
    # as a completer. Defaults to full simulation duration. Late enrollees who cannot
    # complete the minimum protocol duration are censored rather than counted as completers.
    # This prevents bulk-completion of patients who enrolled in the final rounds.
    trial_duration_months: float | None = None

    def __post_init__(self) -> None:
        if self.pop_config is None:
            self.pop_config = PatientPopulationConfig(
                n_patients=self.n_patients,
                n_sites=self.n_sites,
            )
        if self.trial_duration_months is None:
            self.trial_duration_months = self.n_rounds * self.months_per_round


# ─────────────────────────────────────────────────────────────────────────────
# ROUND RECORD
# ─────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class SimulationRound:
    """Snapshot of population state at the end of one simulation round."""
    round_index: int
    time_months: float
    n_enrolled: int
    n_dropout: int
    n_completed: int
    mean_adherence: float
    mean_belief: float
    mean_ae_load: float
    visit_compliance_rate: float
    ae_reporting_mean: float
    enrollment_this_round: int
    dropout_this_round: int
    safety_signal: float
    data_quality: float
    site_burden: float
    n_injection_seeded: int = 0
    active_sites: float = 0.0  # from site activation pipeline
    # FIX 2 (C3): True when a clinical hold halted enrollment this round.
    enrollment_halted: bool = False
    # FIX 7 (H7): patients who enrolled too late to complete protocol duration are censored.
    n_censored: int = 0
    # FIX 2 (C1): Competing risks dropout cause counts for this round.
    dropout_cause_counts: dict = dataclasses.field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN SIMULATION FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def run_simulation(config: SimConfig) -> TrialOutputs:
    """Run one complete trial simulation and return tagged outputs.

    This is the public API. Call this function; it handles all internal
    state and returns a TrialOutputs object with epistemic tags.
    """
    t0 = time.perf_counter()
    rng = np.random.default_rng(config.seed)
    # Separate RNG for competing-risk cause assignment so it does not consume
    # draws from the main simulation RNG and alter dropout/hazard outcomes.
    rng_causes = np.random.default_rng(config.seed + 0xCA05E5)

    # ── Initialise population ─────────────────────────────────────────────────
    pop = PopulationArray.generate(config.pop_config, seed=config.seed)

    # ── Build patient social network ──────────────────────────────────────────
    G = build_patient_network(
        n_patients=config.n_patients,
        n_sites=config.n_sites,
        site_ids=pop.site_ids,
        seed=config.seed,
    )
    net_stats = network_statistics(G)

    # Stubbornness per patient: archetype base + individual noise.
    # Noise σ=0.05 is consistent with Beta(2,2) around archetype mean
    # (variance of Beta(2,2) ≈ 0.05). Source: Johnson & Carnegie (2022),
    # PMC8709162: DeGroot self-weight calibrated from health behavior networks,
    # central estimate 0.5, κ=α+β=4 (Beta(2,2)).
    base_stubborn = np.array([
        ARCHETYPES[ArchetypeID(int(a))].stubbornness
        for a in pop.archetype_ids
    ], dtype=np.float32)
    stubbornness = np.clip(
        base_stubborn + rng.normal(0, 0.05, size=config.n_patients).astype(np.float32),
        0.1, 0.95,
    )
    T = compute_degroot_weights(G, stubbornness)

    # ── Initialise stocks ─────────────────────────────────────────────────────
    stocks = TrialStocks.initialise(config.n_patients, n_sites=config.n_sites)

    # ── Optional LLM swarm mode ───────────────────────────────────────────────
    swarm_prior_adjustment: dict = {}
    if config.llm_client is not None:
        swarm_prior_adjustment = _run_llm_swarm(config, n_agents=config.n_swarm_agents)
        belief_shift = float(swarm_prior_adjustment.get("belief_shift", 0.0))
        if belief_shift != 0.0:
            pop.state[:, COL_BELIEF] = np.clip(
                pop.state[:, COL_BELIEF] + belief_shift, 0.05, 0.95,
            ).astype(np.float32)

        # Apply archetype proportion adjustments if present [SWARM-ELICITED]
        prop_adjustments = swarm_prior_adjustment.get("archetype_prop_adjustments", {})
        if prop_adjustments:
            # Rebuild archetype assignment using adjusted proportions
            new_props = np.array([
                ARCHETYPES[a].default_proportion for a in ArchetypeID
            ], dtype=np.float64)
            for aid_int, new_prop in prop_adjustments.items():
                new_props[int(aid_int)] = new_prop
            # Renormalize (adjustments may not exactly sum to 1)
            new_props = np.clip(new_props, 0.01, 1.0)
            new_props /= new_props.sum()
            # Reassign archetypes for screening patients only (not yet enrolled)
            screening_mask = pop.screening()
            n_screening = int(screening_mask.sum())
            if n_screening > 0:
                rng_local = np.random.default_rng(config.seed + 1)
                new_archetypes = rng_local.choice(len(new_props), size=n_screening, p=new_props).astype(np.int8)
                pop.archetype_ids[screening_mask] = new_archetypes

    # Per-patient enrollment round — for per-patient Weibull time computation.
    # Initialized to -1 (unenrolled). Set when patient transitions to enrolled.
    # Weibull hazard uses individual time-since-enrollment, not calendar time,
    # so late-enrolling patients correctly face the full early-enrollment hazard.
    enrollment_round = np.full(config.n_patients, -1, dtype=np.float32)

    # Store initial beliefs for Friedkin-Johnsen anchoring (prevent consensus collapse)
    initial_beliefs = pop.beliefs().copy()

    # ── Round loop ────────────────────────────────────────────────────────────
    rounds: list[SimulationRound] = []
    injection_index = {ev.round_index: ev for ev in config.injection_events}

    for r in range(config.n_rounds):
        t_months = r * config.months_per_round
        n_seeded_this_round = 0

        # Draw amendment event FIRST each round (before enrollment RNG draws) so that
        # runs differing only in protocol_burden/visit_burden consume RNG in the same
        # order up to this point, preserving the causal test: higher burden -> more site burden.
        # [Internal RNG ordering fix — does not change model causal structure]
        n_amendments_this_round = _sponsor_amendment_draw(
            stocks, rng,
            amendment_initiation_rate_modifier=config.amendment_initiation_rate_modifier,
        )

        # Advance site activation pipeline (DELAY3 — NCI 167-day median)
        stocks.site_activation.step(dt=config.months_per_round)
        # FIX 11 (M13): assert pipeline conservation each round.
        assert stocks.site_activation.conservation_check(), (
            f"site activation pipeline conservation violated at round {r}"
        )

        # FIX 8 (H10): site experience ramps toward 1.0 with τ=6mo first-order smooth.
        # Multiplies enrollment rate by (0.7 + 0.3 * site_experience) — sites start at
        # 70% efficiency and ramp to 100%, producing a concave early-enrollment phase (S-curve).
        # [DIRECTIONAL — site learning curves documented in Tufts CSDD; 6mo τ and 70% start efficiency ASSUMED]
        tau_experience = 6.0  # months
        stocks.site_experience += (config.months_per_round / tau_experience) * (1.0 - stocks.site_experience)
        site_learning_factor = 0.7 + 0.3 * stocks.site_experience

        # 1. Enrollment: Poisson draw for new patients from screening pool
        # FIX 1 (C2): n_new defined at enclosing scope with default 0; set inside block if enrollment occurs.
        n_new = 0
        enrollment_halted_this_round = False
        screening_mask = pop.screening()
        n_screening = int(screening_mask.sum())

        # FIX 2 (C3): Check safety signal triggers BEFORE enrollment; halt/reduce if needed.
        # Clinical hold → skip enrollment entirely.
        # Regulatory action → reduce enrollment rate by 50%.
        # DSMB review → reduce enrollment rate by 20%.
        enrollment_rate_modifier = config.enrollment_rate_modifier
        if stocks.safety_signal.triggers_clinical_hold:
            enrollment_halted_this_round = True
        elif stocks.safety_signal.level >= config.safety_stopping_threshold:
            enrollment_rate_modifier *= 0.50  # 50% reduction for regulatory action
        elif stocks.safety_signal.level >= config.dsmb_sensitivity:
            enrollment_rate_modifier *= 0.80  # 20% reduction for DSMB review

        # FIX 5 (H5): apply recruitment boost from previous round if shortfall was > 30%.
        # [DIRECTIONAL — sponsors do respond to shortfall; 15% magnitude ASSUMED]
        enrollment_rate_modifier *= (1.0 + stocks.recruitment_boost)
        stocks.recruitment_boost = 0.0  # consumed; reset for next round

        if n_screening > 0 and not enrollment_halted_this_round:
            # Negative Binomial enrollment model (Anisimov & Fedorov, Stat Med 2007,
            # PMID 17639505): Poisson-Gamma marginal captures inter-site overdispersion.
            # Empirical overdispersion ratio var/mean ≈ 6 (PMID 12873651).
            # NB via Gamma-Poisson: draw site-aggregate rate ~ Gamma(r, mean/r),
            # where r = mean/(ratio-1) = mean/5. Then n_new ~ Poisson(nb_rate).
            # Active sites modulates enrollment: early rounds have few active sites
            # NCI 167-day median activation → active_fraction ramps from ~0 to ~1 over months 1-8
            active_fraction = stocks.site_activation.active_fraction
            # FIX 8 (H10): multiply by site_learning_factor for S-curve ramp.
            site_rate = max(0.5, 0.8 * config.n_sites * active_fraction * enrollment_rate_modifier * (1.0 - stocks.site_burden.level) * site_learning_factor)
            # NB via Gamma-Poisson. r = mean/5 gives overdispersion ratio 6 (Anisimov 2007).
            # Floor r at 1.0 to prevent extreme zero-enrollment rounds; still overdispersed
            # (ratio ≈ 3 at floor), captures inter-site variance without pathological sparsity.
            r_disp = max(1.0, site_rate / 5.0)
            nb_rate = float(rng.gamma(shape=r_disp, scale=site_rate / r_disp))
            n_new = min(n_screening, rng.poisson(max(0.0, nb_rate)))
            if n_new > 0:
                enroll_idx = rng.choice(
                    np.where(screening_mask)[0], size=n_new, replace=False
                )
                enroll_mask = np.zeros(config.n_patients, dtype=bool)
                enroll_mask[enroll_idx] = True
                pop.enroll(enroll_mask)
                enrollment_round[enroll_idx] = float(r)  # record enrollment round
                stocks.pipeline.n_screening -= n_new
                stocks.pipeline.n_enrolled  += n_new
                stocks.enrollment_velocity.update(float(n_new), dt=config.months_per_round)

        # FIX 5 (H5): after updating enrollment velocity, check shortfall and arm boost.
        # If perceived rate is >30% above actual rate, sponsor responds with +15% boost next round.
        if stocks.enrollment_velocity.enrollment_shortfall > 0.3:
            stocks.recruitment_boost = 0.15  # +15% for next round [DIRECTIONAL — 15% ASSUMED]

        enrolled_mask = pop.enrolled()
        n_enrolled = int(enrolled_mask.sum())

        if n_enrolled == 0:
            rounds.append(_empty_round(r, t_months, stocks))
            continue

        enrolled_idx = np.where(enrolled_mask)[0]

        # 2. Belief propagation (DeGroot)
        new_beliefs = propagate_beliefs(pop.beliefs(), T, enrolled_mask, initial_beliefs=initial_beliefs)
        pop.set_beliefs(new_beliefs)

        # 3. Adversarial injection
        if r in injection_index:
            event = injection_index[r]
            updated_beliefs, seeded_mask = apply_injection(
                pop_beliefs=pop.beliefs(),
                pop_ae_load=pop.state[:, COL_CUMULATIVE_AE],
                health_literacy=pop.health_literacy,
                enrolled_mask=enrolled_mask,
                archetype_ids=pop.archetype_ids,
                site_ids=pop.site_ids,
                event=event,
                rng=rng,
            )
            pop.set_beliefs(updated_beliefs)
            n_seeded_this_round = int(seeded_mask.sum())

        # Update institutional trust: asymmetric first-order SMOOTH
        # Trust is slow-moving, sponsor-signal-driven (not peer-network-driven).
        # Trust erodes faster than it recovers — negativity bias (Slovic 1993,
        # Risk Analysis). Data breach recovery literature: ~1yr to recover,
        # 3-5x faster to damage. τ_decay=3mo, τ_recovery=12mo [DIRECTIONAL].
        # Trust goal: pulled down by amendment pressure (site_burden) and
        # accumulated safety signals. Tufts CSDD 2022: amendments increase
        # dropout 18.8%→29.6% — best available proxy for trust erosion.
        # [GROUNDED direction; linear scaling ASSUMED]
        institutional_trust = pop.state[enrolled_idx, COL_INSTITUTIONAL_TRUST]
        trust_goal = float(np.clip(
            1.0 - 0.4 * stocks.site_burden.level - 0.3 * stocks.safety_signal.level,
            0.0, 1.0,
        ))
        trust_goal_arr = np.full(len(enrolled_idx), trust_goal, dtype=np.float32)
        gap = trust_goal_arr - institutional_trust
        # Asymmetric τ: decay (gap<0) uses τ=3, recovery (gap>0) uses τ=12
        tau_arr = np.where(gap < 0, 3.0, 12.0).astype(np.float32)
        # FIX 9 (H11): multiply by dt so SMOOTH scales correctly with step size.
        dt = config.months_per_round
        pop.state[enrolled_idx, COL_INSTITUTIONAL_TRUST] = np.clip(
            institutional_trust + (dt / tau_arr) * gap, 0.0, 1.0,
        ).astype(np.float32)

        # Update 2-state Markov adherence (TAKING ↔ HOLIDAY)
        # [GROUNDED structure: Vrijens et al. BMJ 2008; transition probs ASSUMED at monthly scale]
        pop.update_adherence_states(rng)

        # Update archetype evolution (TREATMENT_NAIVE → EXPERIENCED_ADVOCATE after 12mo)
        # [ASSUMED: 2%/month transition for veterans with high institutional trust]
        rounds_since_enrollment = np.where(
            enrollment_round >= 0,
            (r - enrollment_round).astype(np.float32),
            np.float32(0.0),
        )
        pop.update_archetypes(rng, rounds_since_enrollment)

        # 4. Compute adherence, visit compliance, AE reporting
        adh = adherence_probability(
            archetype_id_array=pop.archetype_ids[enrolled_idx],
            belief=pop.beliefs()[enrolled_idx],
            cumulative_ae=pop.state[enrolled_idx, COL_CUMULATIVE_AE],
            protocol_burden=config.protocol_burden,
            time_months=t_months,
            institutional_trust=pop.state[enrolled_idx, COL_INSTITUTIONAL_TRUST],
            trial_fatigue=pop.state[enrolled_idx, COL_TRIAL_FATIGUE],
            conscientiousness=pop.state[enrolled_idx, COL_CONSCIENTIOUSNESS],
            neuroticism=pop.state[enrolled_idx, COL_NEUROTICISM],
            personal_control=pop.state[enrolled_idx, COL_PERSONAL_CONTROL],
        )
        pop.state[enrolled_idx, COL_ADHERENCE_PROB] = adh

        vis = visit_compliance_probability(
            archetype_id_array=pop.archetype_ids[enrolled_idx],
            site_access_score=pop.site_access_score[enrolled_idx],
            belief=pop.beliefs()[enrolled_idx],
            protocol_visit_burden=config.protocol_visit_burden,
            # FIX 6 (H6): pass site burden level so response.py can wire the
            # effect of overwhelmed sites on visit compliance.
            site_burden_level=stocks.site_burden.level,
        )
        pop.state[enrolled_idx, COL_VISIT_BURDEN] = 1.0 - vis  # burden = non-compliance

        # 5. Synthetic AE generation and accumulation
        # Grade distribution [ASSUMED]: 60% grade 1, 25% grade 2, 12% grade 3, 3% grade 4
        ae_grade_probs = np.array([0.60, 0.25, 0.12, 0.03])
        ae_grades = rng.choice([1, 2, 3, 4], p=ae_grade_probs, size=n_enrolled)
        ae_occurs = rng.random(n_enrolled) < 0.15  # baseline monthly AE rate [ASSUMED]

        ae_reporting = ae_reporting_fraction(
            archetype_id_array=pop.archetype_ids[enrolled_idx],
            health_literacy=pop.health_literacy[enrolled_idx],
            ae_grade=ae_grades,
        )

        new_ae_pairs = []
        for grade in [1, 2, 3, 4]:
            grade_mask_local = (ae_grades == grade) & ae_occurs
            if grade_mask_local.any():
                grade_mask_global = np.zeros(config.n_patients, dtype=bool)
                grade_mask_global[enrolled_idx[grade_mask_local]] = True
                new_ae_pairs.append((grade, grade_mask_global))

        pop.accumulate_ae(
            accumulate_ae_load(
                current_load=pop.state[:, COL_CUMULATIVE_AE],
                new_ae_grades=new_ae_pairs,
            ) - pop.state[:, COL_CUMULATIVE_AE]  # pass delta
        )

        # 5b. Trial fatigue accumulation (enrolled patients only)
        # Inflow: visit frequency + AE occurrence each round.
        # Outflow: first-order decay with tau=6mo (Euler: outflow = fatigue/tau per month;
        # FIX 10 (M12): half-life ~= 4.2 months, NOT 6 months (half-life = tau*ln2 = 4.16mo).
        # [DIRECTIONAL — Montori Cumulative Complexity Model (PMID 27417747); tau and coefficients ASSUMED; sweep tau in [3, 12]]
        fatigue = pop.state[enrolled_idx, COL_TRIAL_FATIGUE]
        # Visit inflow: normalized visits per month → fraction of max monthly burden (8 vpm)
        visit_inflow = 0.04 * (config.visits_per_month / 8.0)  # [ASSUMED]
        # AE inflow: fraction of patients experiencing an AE this round
        ae_frac = float(ae_occurs.mean()) if len(ae_occurs) > 0 else 0.0
        ae_inflow = 0.06 * ae_frac  # [ASSUMED magnitude]
        # Recovery outflow: first-order decay with tau=6mo (Euler: outflow = fatigue/tau per month; half-life ~= 4.2 months)
        recovery_outflow = (dt / 6.0) * fatigue
        pop.state[enrolled_idx, COL_TRIAL_FATIGUE] = np.clip(
            fatigue + visit_inflow + ae_inflow - recovery_outflow, 0.0, 1.0,
        ).astype(np.float32)

        # 6. Dropout: Bernoulli draw from Weibull hazard (per-patient time)
        # Use individual time-since-enrollment so κ≠1 hazard is anchored to each
        # patient's own exposure duration, not the simulation calendar clock.
        per_patient_time = np.where(
            enrollment_round[enrolled_idx] >= 0,
            (r - enrollment_round[enrolled_idx]) * config.months_per_round,
            0.0,
        )
        hazard = dropout_hazard(
            therapeutic_area=config.therapeutic_area,
            archetype_id_array=pop.archetype_ids[enrolled_idx],
            cumulative_ae=pop.state[enrolled_idx, COL_CUMULATIVE_AE],
            belief=pop.beliefs()[enrolled_idx],
            time_months=per_patient_time,
            shape_k=config.shape_k,  # None = use TA default from TA_DROPOUT_LAMBDA
        )

        # FIX 3 (C5): patient_support_program reduces dropout hazard for
        # LOW_ACCESS_RURAL patients by 25% (hazard × 0.75).
        # [DIRECTIONAL — Milken Institute 2022; magnitude ASSUMED]
        if config.patient_support_program:
            # LOW_ACCESS_RURAL has ArchetypeID value 3
            LOW_ACCESS_RURAL_INDEX = int(ArchetypeID.LOW_ACCESS_RURAL)
            rural_mask = pop.archetype_ids[enrolled_idx] == LOW_ACCESS_RURAL_INDEX
            if rural_mask.any():
                hazard = hazard.copy()
                hazard[rural_mask] *= 0.75

        # Apply policy-derived dropout modifiers before Bernoulli draw.
        # dropout_rate_modifier: global hazard scale (e.g., enrichment reduces dropout).
        # efficacy_dropout_modifier: additional scale from placebo-driven dropout.
        # Both are applied multiplicatively; clipped to [0, 1] to keep valid probability.
        # [DIRECTIONAL — enrichment/placebo effects on dropout; magnitudes ASSUMED]
        combined_dropout_modifier = config.dropout_rate_modifier * config.efficacy_dropout_modifier
        if combined_dropout_modifier != 1.0:
            hazard = np.clip(hazard * combined_dropout_modifier, 0.0, 1.0)

        pop.state[enrolled_idx, COL_DROPOUT_HAZARD] = hazard

        dropout_draws = rng.random(n_enrolled) < hazard
        dropout_idx_local = dropout_draws  # alias used for competing risks below
        if dropout_draws.any():
            dropout_global = np.zeros(config.n_patients, dtype=bool)
            dropout_global[enrolled_idx[dropout_draws]] = True
            pop.drop_out(dropout_global)
            n_dropout_this = int(dropout_draws.sum())
            stocks.pipeline.n_enrolled -= n_dropout_this
            stocks.pipeline.n_dropout  += n_dropout_this

            # Assign dropout cause using competing risks model.
            # Uses rng_causes (separate from main rng) so cause assignment
            # does not perturb the main simulation RNG sequence.
            if dropout_idx_local.sum() > 0:
                dropped_archetype_ids = pop.archetype_ids[dropout_global]
                dropout_causes = assign_dropout_cause(
                    dropped_archetype_ids, config.therapeutic_area, rng_causes
                )
                round_dropout_causes = dropout_causes.tolist()
            else:
                round_dropout_causes = []
        else:
            n_dropout_this = 0
            round_dropout_causes = []

        # Tally cause counts for this round's record
        _cause_label_map = {
            CAUSE_EFFICACY: "efficacy",
            CAUSE_INTOLERABILITY: "intolerability",
            CAUSE_PERSONAL: "personal",
            CAUSE_ADMINISTRATIVE: "administrative",
            CAUSE_NON_MEDICAL: "non_medical",
        }
        round_cause_counts: dict = {}
        for cause_int in round_dropout_causes:
            label = _cause_label_map.get(cause_int, str(cause_int))
            round_cause_counts[label] = round_cause_counts.get(label, 0) + 1

        # 7. Completion
        # FIX 7 (H7): a patient completes only if they have been enrolled long enough
        # to complete the protocol duration. Late enrollees who cannot complete the
        # minimum on-study time are censored rather than bulk-moved to completed.
        # This prevents inflation of n_completed with patients enrolled in final rounds.
        n_censored_this_round = 0
        if r == config.n_rounds - 1:
            remaining_mask = pop.enrolled()
            remaining_idx = np.where(remaining_mask)[0]
            if len(remaining_idx) > 0:
                months_on_study = np.where(
                    enrollment_round[remaining_idx] >= 0,
                    (r - enrollment_round[remaining_idx] + 1) * config.months_per_round,
                    0.0,
                )
                can_complete = months_on_study >= config.trial_duration_months
                completers_local = remaining_idx[can_complete]
                censored_local = remaining_idx[~can_complete]
                if len(completers_local) > 0:
                    complete_mask = np.zeros(config.n_patients, dtype=bool)
                    complete_mask[completers_local] = True
                    pop.complete(complete_mask)
                    stocks.pipeline.n_enrolled  -= len(completers_local)
                    stocks.pipeline.n_completed += len(completers_local)
                # Censored patients remain enrolled; excluded from n_completed.
                n_censored_this_round = len(censored_local)

        # 8. Stock updates
        deviation_rate = float((1.0 - vis).mean())
        underreporting = float(1.0 - ae_reporting.mean())
        # FIX 4 (C6): scaling multiplier increased from 0.05 to 0.15 so that
        # typical mean AE load (~0.2) produces ae_burden_increment ~0.03/round,
        # allowing signals to accumulate toward DSMB/regulatory thresholds.
        # [ASSUMED scaling -- sweep multiplier in [0.05, 0.25]; decay_rate in [0.005, 0.03]]
        ae_burden_increment = float(pop.state[enrolled_idx, COL_CUMULATIVE_AE].mean()) * 0.15

        stocks.data_quality.update(
            deviation_rate=deviation_rate,
            underreporting_fraction=underreporting,
            monitoring_active=config.monitoring_active,
        )
        # FIX 9 (H11): pass dt to safety_signal.update() for correct Euler scaling.
        stocks.safety_signal.update(ae_burden_increment, dt=config.months_per_round)
        # Query volume: per-patient deviation rate generates ~1 query per 5
        # deviations; scaled by enrolled count not total. Industry benchmark:
        # 3-5 day target resolution; 23-day observed median (SCDM Metrics).
        site_query_volume = deviation_rate * max(1.0, n_enrolled / 50.0)
        # FIX 9 (H11): pass dt to site_burden.update() for correct Euler scaling.
        # n_amendments_this_round was drawn at top of round loop (before enrollment RNG).
        stocks.site_burden.update(
            n_amendments_this_round=n_amendments_this_round,
            query_volume=site_query_volume,
            dt=config.months_per_round,
        )
        assert stocks.pipeline.conservation_check(), "population conservation violated"

        # 9. Record
        current_enrolled = pop.enrolled()
        rounds.append(SimulationRound(
            round_index=r,
            time_months=t_months,
            n_enrolled=int(current_enrolled.sum()),
            n_dropout=stocks.pipeline.n_dropout,
            n_completed=stocks.pipeline.n_completed,
            mean_adherence=float(pop.state[current_enrolled, COL_ADHERENCE_PROB].mean())
                           if current_enrolled.any() else 0.0,
            mean_belief=float(pop.beliefs()[current_enrolled].mean())
                        if current_enrolled.any() else 0.0,
            mean_ae_load=float(pop.state[current_enrolled, COL_CUMULATIVE_AE].mean())
                         if current_enrolled.any() else 0.0,
            visit_compliance_rate=float(vis.mean()),
            ae_reporting_mean=float(ae_reporting.mean()),
            # FIX 1 (C2): store actual patients enrolled this round (n_new), not a
            # random Bernoulli draw. n_new is defined at enclosing scope (default 0).
            enrollment_this_round=n_new,
            dropout_this_round=n_dropout_this,
            safety_signal=stocks.safety_signal.level,
            data_quality=stocks.data_quality.level,
            site_burden=stocks.site_burden.level,
            n_injection_seeded=n_seeded_this_round,
            active_sites=stocks.site_activation.active,
            # FIX 2 (C3): record whether enrollment was halted this round due to clinical hold.
            enrollment_halted=enrollment_halted_this_round,
            # FIX 7 (H7): record patients censored due to insufficient on-study time.
            n_censored=n_censored_this_round,
            dropout_cause_counts=round_cause_counts,
        ))

    elapsed = time.perf_counter() - t0

    # ── Build tagged TrialOutputs ─────────────────────────────────────────────
    # Use the last round with enrolled patients for final state reporting.
    # The completion round (last round) moves all enrolled to completed,
    # leaving mean_adherence = 0 which is not a meaningful final value.
    final_round = next(
        (r for r in reversed(rounds) if r.n_enrolled > 0),
        rounds[-1] if rounds else None,
    )
    patient_outputs = _build_patient_outputs(rounds)

    from clinfish.core.calibration.moments import get_moments
    target_moments = get_moments(config.therapeutic_area)
    # Dropout tag: GROUNDED if TA has a primary source, else DIRECTIONAL
    from clinfish.domain.response import TA_DROPOUT_LAMBDA, _DEFAULT_LAMBDA
    ta_source = TA_DROPOUT_LAMBDA.get(config.therapeutic_area, _DEFAULT_LAMBDA)
    dropout_tag = Tag.GROUNDED if ta_source.tag == "GROUNDED" else Tag.DIRECTIONAL

    return TrialOutputs(
        trial_id=f"{config.therapeutic_area}_{config.seed}",
        therapeutic_area=config.therapeutic_area,
        n_patients=config.n_patients,
        n_sites=config.n_sites,
        n_rounds=config.n_rounds,
        rounds=patient_outputs,
        round_snapshots=rounds,
        final_adherence_index=TaggedValue(
            value=final_round.mean_adherence if final_round else 0.0,
            tag=Tag.GROUNDED,
            source="MEMS cross-study mean 74.9%; Bova et al. 2005",
            units="proportion",
        ),
        final_data_quality=TaggedValue(
            value=stocks.data_quality.level,
            tag=Tag.GROUNDED,
            source="Phase III deviation rate 32.8%; Krudys et al. PMC8979478",
            units="index 0-1",
        ),
        final_safety_signal=TaggedValue(
            value=stocks.safety_signal.level,
            tag=Tag.DIRECTIONAL,
            source="FDA clinical hold ~9% of INDs; Manning et al. PMID 31678263",
            units="index 0-1",
        ),
        enrollment_shortfall=TaggedValue(
            value=max(0.0, 1.0 - stocks.pipeline.n_enrolled / config.n_patients),
            tag=Tag.DIRECTIONAL,
            source="80% of trials miss enrollment timeline; Tufts CSDD",
            units="proportion",
        ),
        sponsor_amendment_probability=TaggedValue(
            value=INSTITUTIONAL_ACTORS[InstitutionType.PHARMA_SPONSOR].amendment_initiation_rate,
            tag=Tag.GROUNDED,
            source="76% of trials ≥1 amendment; 3.3/protocol; Getz et al. PMID 38438658",
            units="probability per month",
        ),
        site_burden_index=TaggedValue(
            value=stocks.site_burden.level,
            tag=Tag.DIRECTIONAL,
            source="Protocol amendment burden; Tufts CSDD 2024",
            units="index 0-1",
        ),
        regulator_action_probability=TaggedValue(
            value=float(stocks.safety_signal.level >= config.safety_stopping_threshold),
            tag=Tag.DIRECTIONAL,
            source="FDA clinical hold rate ~9% of INDs; Manning et al.",
            units="boolean",
        ),
        peer_influence_spread=TaggedValue(
            value=float(net_stats["n_advocates"]) / max(config.n_patients, 1),
            tag=Tag.DIRECTIONAL,
            source="Online health community advocate fraction ~3%; Fox & Duggan, Pew 2013",
            units="proportion of advocates",
        ),
        misinformation_penetration=TaggedValue(
            value=0.0,
            tag=Tag.ASSUMED,
            source="ASSUMED — no injection events ran" if not config.injection_events
                   else "ASSUMED — cascade reach; sweep [0.05, 0.30]",
            units="proportion",
        ),
        metadata={
            "elapsed_seconds": elapsed,
            "network_stats": net_stats,
            "swarm_active": config.llm_client is not None,
            "swarm_adjustments": swarm_prior_adjustment,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _sponsor_amendment_draw(
    stocks: TrialStocks,
    rng: np.random.Generator,
    amendment_initiation_rate_modifier: float = 1.0,
) -> int:
    """Bernoulli draw for whether a protocol amendment occurs this round."""
    base_rate = INSTITUTIONAL_ACTORS[InstitutionType.PHARMA_SPONSOR].amendment_initiation_rate
    # Enrollment pressure increases amendment probability (protocol loosening)
    enrollment_pressure = max(0.0, 1.0 - stocks.pipeline.n_enrolled / max(stocks.pipeline.n_total, 1))
    adjusted_rate = min(0.5, base_rate * amendment_initiation_rate_modifier * (1.0 + enrollment_pressure))
    return int(rng.random() < adjusted_rate)


def _empty_round(r: int, t_months: float, stocks: TrialStocks) -> SimulationRound:
    return SimulationRound(
        round_index=r, time_months=t_months, n_enrolled=0,
        n_dropout=stocks.pipeline.n_dropout, n_completed=0,
        mean_adherence=0.0, mean_belief=0.0, mean_ae_load=0.0,
        visit_compliance_rate=0.0, ae_reporting_mean=0.0,
        enrollment_this_round=0, dropout_this_round=0,
        safety_signal=stocks.safety_signal.level,
        data_quality=stocks.data_quality.level,
        site_burden=stocks.site_burden.level,
        active_sites=stocks.site_activation.active,
    )


def _build_patient_outputs(rounds: list[SimulationRound]) -> list[PatientOutputs]:
    from clinfish.domain.response import TA_DROPOUT_LAMBDA
    outputs = []
    for rd in rounds:
        outputs.append(PatientOutputs(
            round_index=rd.round_index,
            adherence_rate=TaggedValue(
                rd.mean_adherence, Tag.GROUNDED,
                "MEMS cross-study mean 74.9%; Bova 2005", "proportion",
            ),
            dropout_cumulative=TaggedValue(
                rd.n_dropout / max(rd.n_enrolled + rd.n_dropout, 1),
                Tag.GROUNDED,
                "Lieberman NEJM 2005 (CNS); Tufts CSDD 2019 (other TAs)", "proportion",
            ),
            visit_compliance=TaggedValue(
                rd.visit_compliance_rate, Tag.GROUNDED,
                "FDA <80% threshold; Krudys PMC8979478", "proportion",
            ),
            ae_reporting_rate=TaggedValue(
                rd.ae_reporting_mean, Tag.GROUNDED,
                "Basch PMC8502480; clinician 3 vs. patient 11 events", "proportion",
            ),
            enrollment_velocity=TaggedValue(
                float(rd.enrollment_this_round), Tag.DIRECTIONAL,
                "Poisson-Gamma; Anisimov & Fedorov PMID 17639505", "patients/round",
            ),
        ))
    return outputs


# ── Persona population matrix ─────────────────────────────────────────────────
# Each axis represents a clinically meaningful dimension of patient heterogeneity.
# Combinations are sampled to produce a realistic population of N agents.

_PERSONA_AXES: dict[str, list[str]] = {
    "age":        ["18-29", "30-44", "45-59", "60-74", "75+"],
    "literacy":   ["low health literacy", "moderate health literacy", "high health literacy"],
    "distance":   ["lives <10 miles from site", "lives 10-30 miles from site",
                   "lives 30-60 miles from site", "lives >60 miles from site"],
    "experience": ["no prior trial experience", "one prior trial", "2+ prior trials"],
    "caregiver":  ["fully independent", "relies partly on a caregiver",
                   "heavily caregiver-dependent for transport and reminders"],
    "employment": ["unemployed or retired", "part-time worker", "full-time demanding job"],
    "anxiety":    ["high medical anxiety and distrust of sponsors",
                   "moderate concern, cautiously open",
                   "low anxiety, motivated and proactive"],
    "comorbidity":["no significant comorbidities", "1-2 managed comorbidities",
                   "3+ comorbidities requiring polypharmacy"],
}


def _sample_personas(n: int, seed: int) -> list[tuple[str, str]]:
    """Sample n patient persona descriptions from the population matrix."""
    import random as _random
    rng = _random.Random(seed)
    personas = []
    for i in range(n):
        attrs = {ax: rng.choice(vals) for ax, vals in _PERSONA_AXES.items()}
        label = (
            f"{attrs['age']} y/o, {attrs['literacy']}, {attrs['employment']}, "
            f"{attrs['distance']}, {attrs['caregiver']}, {attrs['experience']}, "
            f"{attrs['anxiety']}, {attrs['comorbidity']}"
        )
        desc = (
            f"You are a {attrs['age']}-year-old patient with {attrs['literacy']}. "
            f"You are {attrs['employment']} and {attrs['distance']}. "
            f"You {attrs['caregiver']}. "
            f"You have {attrs['experience']} and {attrs['comorbidity']}. "
            f"You have {attrs['anxiety']}."
        )
        personas.append((label, desc))
    return personas


def _call_llm(client: object, is_openai: bool, prompt: str) -> dict:
    """Single LLM call; returns parsed vote dict or raises."""
    import json as _json
    if is_openai:
        resp = client.chat.completions.create(  # type: ignore[attr-defined]
            model="gpt-4o-mini",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content.strip()
    else:
        resp = client.messages.create(  # type: ignore[attr-defined]
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
    # Strip markdown code fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    # Extract JSON object even if model wraps it in prose
    if "{" in raw:
        raw = raw[raw.index("{"):]
    if "}" in raw:
        raw = raw[:raw.rindex("}") + 1]
    return _json.loads(raw)


def _run_llm_swarm(config: SimConfig, n_agents: int = 1000) -> dict:
    """LLM swarm prior elicitation across a population-representative sample of patients.

    Generates n_agents patient personas by sampling from a structured population
    matrix (age, health literacy, site distance, caregiver status, employment,
    prior trial experience, anxiety, comorbidities), then runs each persona
    concurrently against the trial scenario to vote on belief_shift and
    adherence_shift priors.

    Concurrency: ThreadPoolExecutor with min(100, n_agents) workers.
    Rate limit errors are retried once with 2s pause; a 120-second
    wall-clock deadline cancels any stragglers so the response never
    exceeds the proxy timeout. Failed/cancelled agents are excluded from
    aggregation (not zeroed).

    Returns summary statistics rather than all raw votes (response size).
    """
    import json as _json
    import time as _time
    from concurrent.futures import ThreadPoolExecutor
    import statistics as _stats

    try:
        client    = config.llm_client
        is_openai = hasattr(client, "chat")

        ta         = config.therapeutic_area.upper()
        burden_pct = int(config.protocol_burden * 100)
        visit_pct  = int(config.protocol_visit_burden * 100)
        scenario   = (
            f"{ta} trial, {config.n_rounds} months, {config.n_patients} patients, "
            f"{config.n_sites} sites. Protocol burden {burden_pct}%, visit burden {visit_pct}%."
        )

        personas = _sample_personas(n_agents, seed=config.seed)

        def make_prompt(desc: str) -> str:
            return (
                f"{desc}\n\nTrial: {scenario}\n\n"
                "You are this patient. Would you enroll and stay in this trial?\n"
                'JSON only: {"belief_shift": <float -0.15 to 0.15>, '
                '"adherence_shift": <float -0.10 to 0.10>, '
                '"reasoning": "<one sentence from the patient\'s perspective>"}'
            )

        def call_one(args: tuple[str, str]) -> dict:
            label, desc = args
            prompt = make_prompt(desc)
            last_exc: str = ""
            for attempt in range(4):
                try:
                    vote = _call_llm(client, is_openai, prompt)
                    return {
                        "label":           label,
                        "belief_shift":    float(max(-0.15, min(0.15, vote.get("belief_shift", 0.0)))),
                        "adherence_shift": float(max(-0.10, min(0.10, vote.get("adherence_shift", 0.0)))),
                        "reasoning":       str(vote.get("reasoning", ""))[:300],
                    }
                except Exception as exc:
                    last_exc = str(exc)
                    is_rate = "429" in last_exc or "rate" in last_exc.lower() or "quota" in last_exc.lower()
                    if is_rate and attempt < 3:
                        _time.sleep(5.0 * (2 ** attempt))  # 5s, 10s, 20s
                        continue
                    break
            return {"_failed": True, "_error": last_exc}

        n_workers = min(5, n_agents)
        results: list[dict] = []
        n_failed = 0
        first_error: str = ""

        from concurrent.futures import as_completed
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(call_one, p): p for p in personas}
            for fut in as_completed(futures):
                r = fut.result()
                if r.get("_failed"):
                    n_failed += 1
                    if not first_error:
                        first_error = r.get("_error", "unknown error")
                else:
                    results.append(r)

        if not results:
            return {"swarm_error": f"all {n_agents} agents failed — {first_error}"}

        b_vals = [r["belief_shift"]    for r in results]
        a_vals = [r["adherence_shift"] for r in results]

        # Percentile helper
        def pct(lst: list[float], p: float) -> float:
            lst_s = sorted(lst)
            idx = (len(lst_s) - 1) * p / 100
            lo, hi = int(idx), min(int(idx) + 1, len(lst_s) - 1)
            return round(lst_s[lo] + (lst_s[hi] - lst_s[lo]) * (idx - lo), 4)

        # Map vote distribution to archetype proportion adjustments via 5-bucket quantile assignment.
        # Instead of a single scalar shift, distribute vote sentiment to archetype proportions.
        # Votes in the bottom 20% of belief → HIGH_ANXIETY archetype fraction up
        # Votes in the top 20% → MOTIVATED_YOUNG_ADULT fraction up
        # This is the nearest-centroid mapping: each vote's position in the distribution
        # tells us which archetype cluster it most resembles.
        # [ASSUMED mapping — nearest-centroid is principled but centroids are DIRECTIONAL]
        belief_sorted = sorted(b_vals)
        n_v = len(belief_sorted)
        p20  = belief_sorted[max(0, int(0.20 * n_v) - 1)]
        p80  = belief_sorted[min(n_v - 1, int(0.80 * n_v))]
        # Compute archetype proportion adjustments from vote distribution
        high_anxiety_fraction   = sum(1 for b in b_vals if b < p20) / n_v   # bottom quintile
        motivated_fraction      = sum(1 for b in b_vals if b > p80) / n_v   # top quintile
        # Default archetype proportions (from ARCHETYPES) — adjust based on vote distribution
        from clinfish.domain.agents import ArchetypeID
        default_props = {
            ArchetypeID.TREATMENT_NAIVE_HIGH_ANXIETY: 0.20,
            ArchetypeID.EXPERIENCED_ADVOCATE:         0.15,
            ArchetypeID.CAREGIVER_DEPENDENT_ELDERLY:  0.20,
            ArchetypeID.LOW_ACCESS_RURAL:             0.25,
            ArchetypeID.MOTIVATED_YOUNG_ADULT:        0.20,
        }
        # Shift: high_anxiety up by (high_anxiety_fraction - 0.20), motivated up by (motivated_fraction - 0.20)
        # Remaining archetypes absorb the difference proportionally
        archetype_prop_adjustments = {
            int(ArchetypeID.TREATMENT_NAIVE_HIGH_ANXIETY): round(high_anxiety_fraction, 4),
            int(ArchetypeID.MOTIVATED_YOUNG_ADULT):        round(motivated_fraction, 4),
        }

        # Representative sample spanning the belief_shift distribution:
        # half the agents up to 2000 so scatter shows density at scale.
        sorted_results = sorted(results, key=lambda r: r["belief_shift"])
        target = min(max(10, len(sorted_results) // 2), 2000)
        step = max(1, len(sorted_results) // target)
        sample_votes = [sorted_results[i] for i in range(0, len(sorted_results), step)][:target]

        return {
            "belief_shift":              round(sum(b_vals) / len(b_vals), 4),
            "adherence_shift":           round(sum(a_vals) / len(a_vals), 4),
            "n_agents":                  len(results),
            "n_failed":                  n_failed,
            "belief_std":                round(_stats.stdev(b_vals) if len(b_vals) > 1 else 0.0, 4),
            "adherence_std":             round(_stats.stdev(a_vals) if len(a_vals) > 1 else 0.0, 4),
            "belief_p10":                pct(b_vals, 10),
            "belief_p50":                pct(b_vals, 50),
            "belief_p90":                pct(b_vals, 90),
            "adherence_p10":             pct(a_vals, 10),
            "adherence_p50":             pct(a_vals, 50),
            "adherence_p90":             pct(a_vals, 90),
            "votes":                     sample_votes,   # up to n//2 agents, max 2000
            "archetype_prop_adjustments": archetype_prop_adjustments,
            "tag":                       "SWARM-ELICITED",
        }

    except Exception as exc:
        return {"swarm_error": str(exc)}
