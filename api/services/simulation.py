"""Simulation service — bridges API schemas to core engine."""

from __future__ import annotations

import dataclasses
import os
import time

from clinfish.core.engine import SimConfig, run_simulation, SimulationRound
from clinfish.reports.evidence_pack import TrialOutputs, TaggedValue
from clinfish.scenarios import SCENARIO_REGISTRY
from clinfish.social.injection import InjectionEvent, InjectionValence

from api.schemas.request import SimulateRequest, InjectionEventSchema
from api.schemas.response import (
    SimulateResponse,
    RoundSnapshot,
    PatientOutputsOut,
    TaggedValueOut,
)


# ── Burden computation ─────────────────────────────────────────────────────────

_INVASIVE_BURDEN: dict[str, float] = {
    "none":     0.00,
    "blood":    0.05,
    "lp":       0.25,
    "biopsy":   0.20,
    "infusion": 0.15,
}
_EDIARY_BURDEN: dict[str, float] = {
    "none":   0.00,
    "weekly": 0.05,
    "daily":  0.15,
}
_COMP_PRESSURE_EVENTS = {
    "low":    {"round_index": 4, "seed_fraction": 0.10, "target_belief": 0.20},
    "medium": {"round_index": 2, "seed_fraction": 0.20, "target_belief": 0.15},
    "high":   {"round_index": 1, "seed_fraction": 0.35, "target_belief": 0.10},
}


def _compute_protocol_burden(req: SimulateRequest) -> float:
    """Derive 0-1 protocol burden from concrete trial design params.
    Falls back to raw slider value when no concrete params are given.
    """
    if req.visits_per_month is None and req.invasive_procedures is None and req.ediary_frequency is None:
        return req.protocol_burden

    burden = 0.0
    if req.visits_per_month is not None:
        # 0.5 visits/mo = minimal, 8 visits/mo = extreme
        burden += min(1.0, (req.visits_per_month - 0.5) / 7.5) * 0.40
    if req.visit_duration_hours is not None:
        burden += min(1.0, (req.visit_duration_hours - 0.5) / 11.5) * 0.20
    burden += _INVASIVE_BURDEN.get(req.invasive_procedures or "none", 0.10)
    burden += _EDIARY_BURDEN.get(req.ediary_frequency or "none", 0.0)
    if req.patient_support_program:
        burden -= 0.10  # coordinators + transport materially reduce perceived burden
    return max(0.05, min(0.95, burden))


def _compute_visit_burden(req: SimulateRequest) -> float:
    """Derive 0-1 visit burden from visits/month and duration.
    Falls back to raw slider value when visits_per_month is absent.
    """
    if req.visits_per_month is None:
        return req.protocol_visit_burden

    visit_contrib = min(1.0, (req.visits_per_month - 0.5) / 7.5) * 0.75
    dur_contrib = 0.0
    if req.visit_duration_hours is not None:
        dur_contrib = min(1.0, (req.visit_duration_hours - 0.5) / 11.5) * 0.25
    if req.patient_support_program:
        visit_contrib = max(0.0, visit_contrib - 0.10)
    return max(0.05, min(0.95, visit_contrib + dur_contrib))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _schema_to_injection(ev: InjectionEventSchema) -> InjectionEvent:
    return InjectionEvent(
        round_index=ev.round_index,
        target_belief=ev.target_belief,
        seed_fraction=ev.seed_fraction,
        valence=InjectionValence.NEGATIVE if ev.valence == "negative" else InjectionValence.POSITIVE,
        label=ev.label,
        target_archetype_ids=ev.target_archetype_ids,
        target_site_ids=ev.target_site_ids,
    )


def _tagged_value_out(tv: TaggedValue) -> TaggedValueOut:
    return TaggedValueOut(
        value=tv.value,
        tag=tv.tag.value,
        source=tv.source,
        units=tv.units,
    )


def _round_to_schema(r: SimulationRound) -> RoundSnapshot:
    return RoundSnapshot(**dataclasses.asdict(r))


def _collect_warnings(result: TrialOutputs) -> list[str]:
    warnings = []
    rounds = result.round_snapshots
    if not rounds:
        return warnings

    max_safety = max(r.safety_signal for r in rounds)
    if max_safety >= 1.0:
        warnings.append(f"Clinical hold threshold reached (peak safety signal: {max_safety:.2f})")
    elif max_safety >= 0.80:
        warnings.append(f"Regulatory action threshold reached (peak safety signal: {max_safety:.2f})")
    elif max_safety >= 0.50:
        warnings.append(f"DSMB review threshold reached (peak safety signal: {max_safety:.2f})")

    final = rounds[-1]
    if final.n_completed / max(result.n_patients, 1) < 0.30:
        warnings.append(
            f"Low completion rate: {100*final.n_completed/result.n_patients:.1f}% completed"
        )
    if final.data_quality < 0.50:
        warnings.append(f"Data quality critically low: {final.data_quality:.2f}")

    return warnings


def _make_llm_client(openai_api_key: str | None):
    """Return an LLM client for swarm elicitation.

    Priority:
      1. openai_api_key from request body
      2. OPENAI_API_KEY env var  → returns openai.OpenAI client (gpt-4o-mini)
      3. ANTHROPIC_API_KEY env var → returns anthropic.Anthropic client (haiku)
      4. Neither available → returns None (swarm silently skipped)
    """
    oai_key = openai_api_key or os.environ.get("OPENAI_API_KEY", "")
    if oai_key:
        try:
            import openai
            return openai.OpenAI(api_key=oai_key)
        except ImportError:
            pass

    ant_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if ant_key:
        try:
            import anthropic
            return anthropic.Anthropic(api_key=ant_key)
        except ImportError:
            pass

    return None


# ── Main service function ──────────────────────────────────────────────────────

def run_simulation_request(req: SimulateRequest) -> SimulateResponse:
    t0 = time.perf_counter()

    protocol_burden    = _compute_protocol_burden(req)
    visit_burden       = _compute_visit_burden(req)

    # Compute final enrollment rate modifier accounting for adaptive design and enrichment
    enroll_rate_mod = req.enrollment_rate_modifier
    enrichment = getattr(req, "enrichment_factor", 0.0) or 0.0
    if getattr(req, "adaptive_design_enabled", False):
        enroll_rate_mod = round(enroll_rate_mod * 1.10, 3)   # 10% adaptive design boost [DIRECTIONAL]
    if enrichment > 0:
        enroll_rate_mod = round(enroll_rate_mod * (1.0 - 0.30 * enrichment), 3)  # enrichment slows enrollment

    if req.use_preset and req.therapeutic_area in SCENARIO_REGISTRY:
        config = SCENARIO_REGISTRY[req.therapeutic_area]()
        config.n_patients            = req.n_patients
        config.n_sites               = req.n_sites
        config.n_rounds              = req.n_rounds
        config.protocol_burden       = protocol_burden
        config.protocol_visit_burden = visit_burden
        config.monitoring_active     = req.monitoring_active
        config.seed                  = req.seed
        config.enrollment_rate_modifier      = enroll_rate_mod
        config.patient_support_program       = req.patient_support_program
        config.amendment_initiation_rate_modifier = req.amendment_initiation_rate_modifier
        config.dropout_rate_modifier         = req.dropout_rate_modifier * (1.0 - 0.20 * enrichment) if enrichment > 0 else req.dropout_rate_modifier
        config.efficacy_dropout_modifier     = req.efficacy_dropout_modifier
        config.dsmb_sensitivity              = req.dsmb_sensitivity
        config.safety_stopping_threshold     = req.safety_stopping_threshold
        config.injection_events              = [_schema_to_injection(e) for e in req.injection_events]
        if req.visits_per_month is not None:
            config.visits_per_month = req.visits_per_month
        if config.pop_config is not None:
            config.pop_config.n_patients = req.n_patients
            config.pop_config.n_sites    = req.n_sites
    else:
        config = SimConfig(
            therapeutic_area=req.therapeutic_area,
            n_patients=req.n_patients,
            n_sites=req.n_sites,
            n_rounds=req.n_rounds,
            protocol_burden=protocol_burden,
            protocol_visit_burden=visit_burden,
            monitoring_active=req.monitoring_active,
            seed=req.seed,
            enrollment_rate_modifier=enroll_rate_mod,
            injection_events=[_schema_to_injection(e) for e in req.injection_events],
            # Policy-derived modifiers — all now properly wired from request schema to engine
            patient_support_program=req.patient_support_program,
            visits_per_month=req.visits_per_month if req.visits_per_month is not None else 2.0,
            amendment_initiation_rate_modifier=req.amendment_initiation_rate_modifier,
            dropout_rate_modifier=req.dropout_rate_modifier * (1.0 - 0.20 * enrichment) if enrichment > 0 else req.dropout_rate_modifier,
            efficacy_dropout_modifier=req.efficacy_dropout_modifier,
            dsmb_sensitivity=req.dsmb_sensitivity,
            safety_stopping_threshold=req.safety_stopping_threshold,
        )

    # ── Competitive pressure → inject negative belief event ───────────────────
    pressure = req.competitive_pressure or "none"
    if pressure != "none" and pressure in _COMP_PRESSURE_EVENTS:
        ev_params = _COMP_PRESSURE_EVENTS[pressure]
        if ev_params["round_index"] < req.n_rounds:
            config.injection_events.append(InjectionEvent(
                round_index=ev_params["round_index"],
                target_belief=ev_params["target_belief"],
                seed_fraction=ev_params["seed_fraction"],
                valence=InjectionValence.NEGATIVE,
                label=f"Competitive pressure ({pressure})",
            ))

    # ── LLM swarm elicitation ──────────────────────────────────────────────────
    if req.use_swarm:
        config.llm_client    = _make_llm_client(req.openai_api_key)
        config.n_swarm_agents = req.n_swarm_agents

    result = run_simulation(config)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    patient_outs = []
    for po in result.rounds:
        patient_outs.append(PatientOutputsOut(
            adherence_rate=_tagged_value_out(po.adherence_rate),
            dropout_cumulative=_tagged_value_out(po.dropout_cumulative),
            visit_compliance=_tagged_value_out(po.visit_compliance),
            ae_reporting_rate=_tagged_value_out(po.ae_reporting_rate),
            enrollment_velocity=_tagged_value_out(po.enrollment_velocity),
        ))

    final_stocks: dict[str, float] = {}
    if result.round_snapshots:
        last = result.round_snapshots[-1]
        final_stocks = {
            "safety_signal": last.safety_signal,
            "data_quality":  last.data_quality,
            "site_burden":   last.site_burden,
        }

    raw_network_stats = result.metadata.get("network_stats", {})
    network_stats = {
        k: float(v) if hasattr(v, "__float__") else int(v) if hasattr(v, "__int__") else v
        for k, v in raw_network_stats.items()
    }
    swarm_meta = result.metadata.get("swarm_adjustments") or None

    return SimulateResponse(
        therapeutic_area=result.therapeutic_area,
        n_patients=result.n_patients,
        n_sites=result.n_sites,
        n_rounds=result.n_rounds,
        elapsed_ms=round(elapsed_ms, 2),
        assumed_count=result.assumed_count(),
        round_snapshots=[_round_to_schema(r) for r in result.round_snapshots],
        patient_outputs=patient_outs,
        network_stats=network_stats,
        final_stocks=final_stocks,
        warnings=_collect_warnings(result),
        swarm_metadata=swarm_meta,
    )
