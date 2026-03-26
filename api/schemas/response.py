"""Response schemas for the ClinFish REST API."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict


class RoundSnapshot(BaseModel):
    round_index:           int
    time_months:           float
    n_enrolled:            int
    n_dropout:             int
    n_completed:           int
    mean_adherence:        float
    mean_belief:           float
    mean_ae_load:          float
    visit_compliance_rate: float
    ae_reporting_mean:     float
    enrollment_this_round: int
    dropout_this_round:    int
    safety_signal:         float
    data_quality:          float
    site_burden:           float
    n_injection_seeded:    int
    # Fields added to SimulationRound after initial schema — now surfaced in API responses
    active_sites:          float = 0.0     # fraction of sites through activation pipeline
    enrollment_halted:     bool  = False   # True when clinical hold paused enrollment
    n_censored:            int   = 0       # late enrollees who could not complete protocol
    dropout_cause_counts:  dict  = {}      # {cause_name: count} per round from competing risks


class TaggedValueOut(BaseModel):
    value: float
    tag:   str    # "GROUNDED" | "DIRECTIONAL" | "ASSUMED"
    source: str
    units:  str


class PatientOutputsOut(BaseModel):
    adherence_rate:       TaggedValueOut
    dropout_cumulative:   TaggedValueOut
    visit_compliance:     TaggedValueOut
    ae_reporting_rate:    TaggedValueOut
    enrollment_velocity:  TaggedValueOut


class SimulateResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    therapeutic_area: str
    n_patients:       int
    n_sites:          int
    n_rounds:         int
    elapsed_ms:       float
    assumed_count:    int

    round_snapshots:  list[RoundSnapshot]
    patient_outputs:  list[PatientOutputsOut]

    network_stats:    dict[str, Any]
    final_stocks:     dict[str, float]
    warnings:         list[str]
    swarm_metadata:   Optional[dict[str, Any]] = None


class CompareResponse(BaseModel):
    scenario_a: SimulateResponse
    scenario_b: SimulateResponse
    delta:      dict[str, float]   # key metric deltas (a - b)


class CalibrateResponse(BaseModel):
    therapeutic_area: str
    best_params:      list[float]
    best_distance:    float
    elapsed_seconds:  float
    moment_names:     list[str]
    target_values:    list[float]


class PresetResponse(BaseModel):
    therapeutic_area:      str
    n_patients:            int
    n_sites:               int
    n_rounds:              int
    protocol_burden:       float
    protocol_visit_burden: float
    description:           str
