"""Request schemas for the ClinFish REST API."""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator


class InjectionEventSchema(BaseModel):
    round_index: int = Field(..., ge=0, description="Round (month) at which injection fires")
    target_belief: float = Field(..., ge=0.0, le=1.0)
    seed_fraction: float = Field(0.10, ge=0.0, le=1.0,
                                 description="Fraction of enrolled patients seeded")
    valence: Literal["negative", "positive"] = "negative"
    label: str = Field("", max_length=120)
    target_archetype_ids: Optional[list[int]] = None
    target_site_ids:      Optional[list[int]] = None


class SimulateRequest(BaseModel):
    therapeutic_area: Literal[
        "cns", "cardiovascular", "oncology", "metabolic", "alzheimers", "rare", "other"
    ]
    n_patients: int = Field(400, ge=10,  le=10_000)
    n_sites:    int = Field(20,  ge=1,   le=500)
    n_rounds:   int = Field(18,  ge=1,   le=120)

    # ── Concrete visit schedule ────────────────────────────────────────────────
    visits_per_month:     Optional[float] = Field(
        None, ge=0.5, le=8.0,
        description="Scheduled clinic visits per calendar month (0.5 = bimonthly, 4 = weekly)")
    visit_duration_hours: Optional[float] = Field(
        None, ge=0.5, le=12.0,
        description="Mean hours per clinic visit including travel, waiting, and procedures")
    invasive_procedures:  Optional[Literal["none", "blood", "lp", "biopsy", "infusion"]] = Field(
        None,
        description="Most burdensome invasive procedure: none, blood draw, lumbar puncture, biopsy, or long infusion")
    ediary_frequency:     Optional[Literal["none", "weekly", "daily"]] = Field(
        None,
        description="Electronic patient-reported outcome diary frequency")

    # ── Site & operations ──────────────────────────────────────────────────────
    monitoring_active:       bool = Field(True,  description="Risk-based monitoring / SDV enabled")
    site_quality_variance:   Optional[Literal["low", "medium", "high"]] = Field(
        None,
        description="Heterogeneity in site performance (low = uniform, high = some sites struggle)")
    patient_support_program: bool = Field(
        False,
        description="Dedicated patient coordinators, transport reimbursement, and reminder systems")

    # ── Trial design ───────────────────────────────────────────────────────────
    randomization_ratio:   Optional[Literal["1:1", "2:1", "3:1"]] = Field(
        None,
        description="Treatment:placebo randomization ratio")
    blinded:               bool = Field(True, description="Double-blind trial")
    competitive_pressure:  Optional[Literal["none", "low", "medium", "high"]] = Field(
        None,
        description="Rival trials recruiting same population / negative social media events")
    enrollment_rate_modifier: float = Field(
        1.0, ge=0.1, le=3.0,
        description="Multiplier on baseline TA enrollment rate (1.0 = TA default)")

    # ── Legacy abstract burden sliders (used when concrete params absent) ──────
    protocol_burden:       float = Field(0.50, ge=0.0, le=1.0)
    protocol_visit_burden: float = Field(0.50, ge=0.0, le=1.0)

    # ── Policy-derived modifiers ───────────────────────────────────────────────
    amendment_initiation_rate_modifier: float = Field(
        1.0, ge=0.1, le=3.0,
        description="Multiplier on base amendment probability (1.0 = TA default)")
    adaptive_design_enabled: bool = Field(
        False,
        description="Whether adaptive design elements are active")
    enrichment_factor: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Biomarker enrichment level (0=broad eligibility, 1=fully enriched)")
    dropout_rate_modifier: float = Field(
        1.0, ge=0.1, le=2.0,
        description="Multiplier on per-patient dropout hazard (1.0 = no change)")
    efficacy_dropout_modifier: float = Field(
        1.0, ge=0.5, le=2.0,
        description="Additional dropout multiplier from lack-of-efficacy (placebo-driven)")
    dsmb_sensitivity: float = Field(
        0.50, ge=0.1, le=1.0,
        description="Safety signal threshold for DSMB review trigger (lower = more sensitive)")
    safety_stopping_threshold: float = Field(
        0.80, ge=0.1, le=1.0,
        description="Safety signal threshold for regulatory action (higher = more conservative)")

    use_preset: bool = Field(True,  description="Seed from TA calibrated preset")
    seed:       int  = Field(0,     ge=0)

    use_swarm:      bool           = Field(False, description="Run LLM swarm prior elicitation")
    n_swarm_agents: int            = Field(1000,  ge=10, le=5000)
    openai_api_key: Optional[str]  = Field(None,  description="OpenAI key (overrides env var)")

    injection_events: list[InjectionEventSchema] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_injections(self) -> "SimulateRequest":
        for ev in self.injection_events:
            if ev.round_index >= self.n_rounds:
                raise ValueError(
                    f"Injection round_index {ev.round_index} "
                    f"exceeds n_rounds {self.n_rounds}"
                )
        return self


class CompareRequest(BaseModel):
    """Run two simulations and return a side-by-side comparison."""
    scenario_a: SimulateRequest
    scenario_b: SimulateRequest


class CalibrateRequest(BaseModel):
    therapeutic_area: Literal[
        "cns", "cardiovascular", "oncology", "metabolic", "alzheimers", "rare"
    ]
    n_lhs_samples: int = Field(300, ge=50, le=2000)
