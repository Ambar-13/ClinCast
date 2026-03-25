"""Evidence service — expose calibration sources and preset metadata."""

from __future__ import annotations

from clinfish.core.calibration.moments import MOMENT_REGISTRY, get_moments
from clinfish.scenarios import SCENARIO_REGISTRY

from api.schemas.response import PresetResponse


_SCENARIO_DESCRIPTIONS = {
    "cns": (
        "CNS schizophrenia/psychosis Phase 3. "
        "Calibrated to CATIE (NEJM 2005, n=1,493). "
        "74% all-cause discontinuation at 18 months."
    ),
    "oncology": (
        "Oncology Phase 3. "
        "Calibrated to Tufts CSDD 2019 late-phase survey. "
        "Protocol deviation rate 46.6% of patients (Krudys 2022)."
    ),
    "cardiovascular": (
        "Cardiovascular Phase 3. "
        "Calibrated to CHARM Overall (Lancet 2003, n=7,599) and MERIT-HF (n=3,991). "
        "21% dropout at 24 months."
    ),
    "metabolic": (
        "Metabolic/T2DM Phase 3. "
        "Calibrated to AACT database (~31% overall dropout). "
        "Vrijens 2008 antihypertensive adherence proxy."
    ),
    "alzheimers": (
        "Alzheimer's disease Phase 3. "
        "Calibrated to A4 Study (Donohue 2020, n=4,486) and "
        "Phase 3 AD meta-analysis (21.2% ± 10.8% at 1.4 years, n=8,103)."
    ),
    "rare": (
        "Rare disease Phase 3. "
        "Calibrated to Tufts CSDD 2019 orphan drug survey. "
        "6.5% cumulative dropout at 24 months."
    ),
}


def get_preset_metadata(therapeutic_area: str) -> PresetResponse:
    config = SCENARIO_REGISTRY[therapeutic_area]()
    return PresetResponse(
        therapeutic_area=therapeutic_area,
        n_patients=config.n_patients,
        n_sites=config.n_sites,
        n_rounds=config.n_rounds,
        protocol_burden=config.protocol_burden,
        protocol_visit_burden=config.protocol_visit_burden,
        description=_SCENARIO_DESCRIPTIONS.get(therapeutic_area, ""),
    )


def list_presets() -> list[PresetResponse]:
    return [get_preset_metadata(ta) for ta in SCENARIO_REGISTRY]


def get_evidence_summary(therapeutic_area: str) -> dict:
    """Return calibration moments and their sources for a TA."""
    moments = get_moments(therapeutic_area)
    return {
        "therapeutic_area": therapeutic_area,
        "moments": [
            {
                "name": name,
                "target": float(val),
                "standard_error": float(se),
            }
            for name, val, se in zip(moments.names, moments.values, moments.ses)
        ],
    }
