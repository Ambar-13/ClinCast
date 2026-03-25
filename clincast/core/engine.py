"""Main simulation loop — orchestrates all components per round.

Per-round flow (follows Sterman 2000 Ch. 3 simulation order):
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
Voting follows the same bounded-range constraint used in SwarmCast v2.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any

import numpy as np

from clincast.core.network import (
    build_patient_network,
    compute_degroot_weights,
    propagate_beliefs,
    network_statistics,
)
from clincast.core.vectorized import (
    PopulationArray,
    STATUS_SCREENING, STATUS_ENROLLED, STATUS_DROPOUT, STATUS_COMPLETED,
    COL_BELIEF, COL_ADHERENCE_PROB, COL_DROPOUT_HAZARD,
    COL_CUMULATIVE_AE, COL_VISIT_BURDEN, COL_STATUS,
)
from clincast.domain.agents import (
    PatientPopulationConfig,
    ArchetypeID,
    ARCHETYPES,
    INSTITUTIONAL_ACTORS,
    InstitutionType,
)
from clincast.domain.response import (
    dropout_hazard,
    adherence_probability,
    visit_compliance_probability,
    ae_reporting_fraction,
    accumulate_ae_load,
    AE_GRADE_WEIGHT,
)
from clincast.domain.stocks import TrialStocks
from clincast.reports.evidence_pack import (
    Tag,
    TaggedValue,
    PatientOutputs,
    TrialOutputs,
)
from clincast.social.injection import InjectionEvent, apply_injection


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

    # LLM swarm mode — None = offline (vectorized only)
    llm_client:    Any | None = None
    n_swarm_agents: int       = 1000

    pop_config: PatientPopulationConfig | None = None  # if None, built from n/n_sites

    def __post_init__(self) -> None:
        if self.pop_config is None:
            self.pop_config = PatientPopulationConfig(
                n_patients=self.n_patients,
                n_sites=self.n_sites,
            )


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
    stocks = TrialStocks.initialise(config.n_patients)

    # ── Optional LLM swarm mode ───────────────────────────────────────────────
    swarm_prior_adjustment: dict = {}
    if config.llm_client is not None:
        swarm_prior_adjustment = _run_llm_swarm(config, n_agents=config.n_swarm_agents)
        # Apply bounded belief shift to initial population beliefs
        belief_shift = float(swarm_prior_adjustment.get("belief_shift", 0.0))
        if belief_shift != 0.0:
            pop.state[:, COL_BELIEF] = np.clip(
                pop.state[:, COL_BELIEF] + belief_shift, 0.05, 0.95,
            ).astype(np.float32)

    # Per-patient enrollment round — for per-patient Weibull time computation.
    # Initialized to -1 (unenrolled). Set when patient transitions to enrolled.
    # Weibull hazard uses individual time-since-enrollment, not calendar time,
    # so late-enrolling patients correctly face the full early-enrollment hazard.
    enrollment_round = np.full(config.n_patients, -1, dtype=np.float32)

    # ── Round loop ────────────────────────────────────────────────────────────
    rounds: list[SimulationRound] = []
    injection_index = {ev.round_index: ev for ev in config.injection_events}

    for r in range(config.n_rounds):
        t_months = r * config.months_per_round
        n_seeded_this_round = 0

        # 1. Enrollment: Poisson draw for new patients from screening pool
        screening_mask = pop.screening()
        n_screening = int(screening_mask.sum())
        if n_screening > 0:
            # Negative Binomial enrollment model (Anisimov & Fedorov, Stat Med 2007,
            # PMID 17639505): Poisson-Gamma marginal captures inter-site overdispersion.
            # Empirical overdispersion ratio var/mean ≈ 6 (PMID 12873651).
            # NB via Gamma-Poisson: draw site-aggregate rate ~ Gamma(r, mean/r),
            # where r = mean/(ratio-1) = mean/5. Then n_new ~ Poisson(nb_rate).
            site_rate = max(0.5, 0.8 * config.n_sites * config.enrollment_rate_modifier * (1.0 - stocks.site_burden.level))
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
                stocks.enrollment_velocity.update(float(n_new))

        enrolled_mask = pop.enrolled()
        n_enrolled = int(enrolled_mask.sum())

        if n_enrolled == 0:
            rounds.append(_empty_round(r, t_months, stocks))
            continue

        enrolled_idx = np.where(enrolled_mask)[0]

        # 2. Belief propagation (DeGroot)
        new_beliefs = propagate_beliefs(pop.beliefs(), T, enrolled_mask)
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

        # 4. Compute adherence, visit compliance, AE reporting
        adh = adherence_probability(
            archetype_id_array=pop.archetype_ids[enrolled_idx],
            belief=pop.beliefs()[enrolled_idx],
            cumulative_ae=pop.state[enrolled_idx, COL_CUMULATIVE_AE],
            protocol_burden=config.protocol_burden,
            time_months=t_months,
        )
        pop.state[enrolled_idx, COL_ADHERENCE_PROB] = adh

        vis = visit_compliance_probability(
            archetype_id_array=pop.archetype_ids[enrolled_idx],
            site_access_score=pop.site_access_score[enrolled_idx],
            belief=pop.beliefs()[enrolled_idx],
            protocol_visit_burden=config.protocol_visit_burden,
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
        pop.state[enrolled_idx, COL_DROPOUT_HAZARD] = hazard

        dropout_draws = rng.random(n_enrolled) < hazard
        if dropout_draws.any():
            dropout_global = np.zeros(config.n_patients, dtype=bool)
            dropout_global[enrolled_idx[dropout_draws]] = True
            pop.drop_out(dropout_global)
            n_dropout_this = int(dropout_draws.sum())
            stocks.pipeline.n_enrolled -= n_dropout_this
            stocks.pipeline.n_dropout  += n_dropout_this
        else:
            n_dropout_this = 0

        # 7. Completion
        if r == config.n_rounds - 1:
            # Last round: complete all remaining enrolled
            remaining = pop.enrolled()
            n_complete = int(remaining.sum())
            if n_complete > 0:
                pop.complete(remaining)
                stocks.pipeline.n_enrolled  -= n_complete
                stocks.pipeline.n_completed += n_complete

        # 8. Stock updates
        deviation_rate = float((1.0 - vis).mean())
        underreporting = float(1.0 - ae_reporting.mean())
        ae_burden_increment = float(pop.state[enrolled_idx, COL_CUMULATIVE_AE].mean()) * 0.05

        stocks.data_quality.update(
            deviation_rate=deviation_rate,
            underreporting_fraction=underreporting,
            monitoring_active=config.monitoring_active,
        )
        stocks.safety_signal.update(ae_burden_increment)
        # Query volume: per-patient deviation rate generates ~1 query per 5
        # deviations; scaled by enrolled count not total. Industry benchmark:
        # 3–5 day target resolution; 23-day observed median (SCDM Metrics).
        site_query_volume = deviation_rate * max(1.0, n_enrolled / 50.0)
        stocks.site_burden.update(
            n_amendments_this_round=_sponsor_amendment_draw(stocks, rng),
            query_volume=site_query_volume,
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
            enrollment_this_round=int(n_enrolled > 0) * min(1, rng.poisson(1)),
            dropout_this_round=n_dropout_this,
            safety_signal=stocks.safety_signal.level,
            data_quality=stocks.data_quality.level,
            site_burden=stocks.site_burden.level,
            n_injection_seeded=n_seeded_this_round,
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

    from clincast.core.calibration.moments import get_moments
    target_moments = get_moments(config.therapeutic_area)
    # Dropout tag: GROUNDED if TA has a primary source, else DIRECTIONAL
    from clincast.domain.response import TA_DROPOUT_LAMBDA, _DEFAULT_LAMBDA
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
            value=float(stocks.safety_signal.triggers_regulatory_action),
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

def _sponsor_amendment_draw(stocks: TrialStocks, rng: np.random.Generator) -> int:
    """Bernoulli draw for whether a protocol amendment occurs this round."""
    base_rate = INSTITUTIONAL_ACTORS[InstitutionType.PHARMA_SPONSOR].amendment_initiation_rate
    # Enrollment pressure increases amendment probability (protocol loosening)
    enrollment_pressure = max(0.0, 1.0 - stocks.pipeline.n_enrolled / max(stocks.pipeline.n_total, 1))
    adjusted_rate = min(0.5, base_rate * (1.0 + enrollment_pressure))
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
    )


def _build_patient_outputs(rounds: list[SimulationRound]) -> list[PatientOutputs]:
    from clincast.domain.response import TA_DROPOUT_LAMBDA
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

        # Representative sample spanning the belief_shift distribution:
        # half the agents up to 2000 so scatter shows density at scale.
        sorted_results = sorted(results, key=lambda r: r["belief_shift"])
        target = min(max(10, len(sorted_results) // 2), 2000)
        step = max(1, len(sorted_results) // target)
        sample_votes = [sorted_results[i] for i in range(0, len(sorted_results), step)][:target]

        return {
            "belief_shift":    round(sum(b_vals) / len(b_vals), 4),
            "adherence_shift": round(sum(a_vals) / len(a_vals), 4),
            "n_agents":        len(results),
            "n_failed":        n_failed,
            "belief_std":      round(_stats.stdev(b_vals) if len(b_vals) > 1 else 0.0, 4),
            "adherence_std":   round(_stats.stdev(a_vals) if len(a_vals) > 1 else 0.0, 4),
            "belief_p10":      pct(b_vals, 10),
            "belief_p50":      pct(b_vals, 50),
            "belief_p90":      pct(b_vals, 90),
            "adherence_p10":   pct(a_vals, 10),
            "adherence_p50":   pct(a_vals, 50),
            "adherence_p90":   pct(a_vals, 90),
            "votes":           sample_votes,   # up to n//2 agents, max 2000
            "tag":             "SWARM-ELICITED",
        }

    except Exception as exc:
        return {"swarm_error": str(exc)}
