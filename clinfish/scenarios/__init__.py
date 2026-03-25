"""Pre-configured simulation scenarios by therapeutic area.

Each scenario returns a SimConfig tuned to the typical trial characteristics
of that disease area, grounded in published trial size and duration data.

Usage:
    from clinfish.scenarios import cns, oncology
    result = run_simulation(cns.default())
"""

from clinfish.scenarios.cns import default as cns_default
from clinfish.scenarios.oncology import default as oncology_default
from clinfish.scenarios.cardiovascular import default as cardiovascular_default
from clinfish.scenarios.metabolic import default as metabolic_default
from clinfish.scenarios.alzheimers import default as alzheimers_default
from clinfish.scenarios.rare import default as rare_default

SCENARIO_REGISTRY: dict[str, object] = {
    "cns":            cns_default,
    "oncology":       oncology_default,
    "cardiovascular": cardiovascular_default,
    "metabolic":      metabolic_default,
    "alzheimers":     alzheimers_default,
    "rare":           rare_default,
}


def get_scenario(therapeutic_area: str):
    """Return the default SimConfig factory for a therapeutic area."""
    factory = SCENARIO_REGISTRY.get(therapeutic_area)
    if factory is None:
        raise KeyError(
            f"Unknown therapeutic area '{therapeutic_area}'. "
            f"Available: {list(SCENARIO_REGISTRY)}"
        )
    return factory()
