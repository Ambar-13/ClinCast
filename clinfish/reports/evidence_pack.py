"""Output evidence pack — every number with its epistemic provenance.

ESTIMAND CONTEXT (ICH E9(R1), FDA November 2019)
──────────────────────────────────────────────────
ClinFish outputs correspond to the ICH E9(R1) "treatment policy" estimand
(Section 3.2.1): behavior of the assigned-treatment population regardless
of adherence or intercurrent events (ITT-aligned). Dropout and adherence
outputs are also interpretable as "while on treatment" estimands (Section
3.2.3). Tags on every output value (GROUNDED/DIRECTIONAL/ASSUMED) provide
the epistemic provenance required for FDA Model-Informed Drug Development
(MIDD) submissions under the MIDD Paired Meeting Pilot Program.

FDA MIDD QUALIFICATION
───────────────────────
ClinFish qualifies structurally as a MIDD-compliant simulation tool under
the FDA Center for Drug Evaluation and Research (CDER) MIDD program (2017):
  - Mechanistic model with transparent parameter sourcing (all GROUNDED/
    DIRECTIONAL/ASSUMED tags with citations)
  - Validation via Barlas (1996) structure tests + Theil U decomposition
  - Uncertainty quantification via SMM calibration (Lamperti 2018)
Not yet formally qualified — formal qualification requires FDA engagement.
"""

from __future__ import annotations

import dataclasses
import json
from enum import Enum
from typing import Any


class Tag(str, Enum):
    GROUNDED    = "GROUNDED"
    DIRECTIONAL = "DIRECTIONAL"
    ASSUMED     = "ASSUMED"


@dataclasses.dataclass
class TaggedValue:
    value: float
    tag: Tag
    source: str       # citation or "ASSUMED — sweep [lo, hi]"
    units: str = ""

    def __repr__(self) -> str:
        return f"{self.value:.4g} [{self.tag.value}] ({self.source})"


@dataclasses.dataclass
class PatientOutputs:
    """Per-round population-level outputs from one simulation run."""

    round_index: int
    adherence_rate: TaggedValue         # fraction of enrolled patients on schedule
    dropout_cumulative: TaggedValue     # cumulative dropout proportion
    visit_compliance: TaggedValue       # fraction meeting ≥80% visit threshold
    ae_reporting_rate: TaggedValue      # fraction of grade 1-2 AEs actually reported
    enrollment_velocity: TaggedValue    # new patients enrolled this round


@dataclasses.dataclass
class TrialOutputs:
    """Top-level outputs for one complete trial simulation."""

    trial_id: str
    therapeutic_area: str
    n_patients: int
    n_sites: int
    n_rounds: int

    # Per-round tagged outputs (one PatientOutputs per round)
    rounds: list[PatientOutputs]

    # Terminal stocks
    final_adherence_index: TaggedValue
    final_data_quality: TaggedValue
    final_safety_signal: TaggedValue
    enrollment_shortfall: TaggedValue   # fraction of target not reached

    # Institutional layer
    sponsor_amendment_probability: TaggedValue
    site_burden_index: TaggedValue
    regulator_action_probability: TaggedValue

    # Social layer
    peer_influence_spread: TaggedValue  # belief propagation reach
    misinformation_penetration: TaggedValue

    # Raw round snapshots from the simulation loop (SimulationRound objects).
    # Typed as list to avoid circular import with engine.py.
    round_snapshots: list = dataclasses.field(default_factory=list)

    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_json(self, indent: int = 2) -> str:
        def _serialize(obj: Any) -> Any:
            if isinstance(obj, TaggedValue):
                return {
                    "value": obj.value,
                    "tag": obj.tag.value,
                    "source": obj.source,
                    "units": obj.units,
                }
            if isinstance(obj, PatientOutputs):
                return dataclasses.asdict(obj)
            if isinstance(obj, list):
                return [_serialize(x) for x in obj]
            if isinstance(obj, dict):
                return {k: _serialize(v) for k, v in obj.items()}
            return obj

        return json.dumps(_serialize(dataclasses.asdict(self)), indent=indent)

    def assumed_count(self) -> int:
        """Number of ASSUMED-tagged outputs in this result set."""
        count = 0
        for field in dataclasses.fields(self):
            val = getattr(self, field.name)
            if isinstance(val, TaggedValue) and val.tag == Tag.ASSUMED:
                count += 1
        return count
