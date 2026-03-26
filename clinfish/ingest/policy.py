"""Sponsor policy-to-parameter translation layer.

Maps 15 sponsor strategic dimensions to concrete SimConfig adjustments.
Each dimension has a range [min, max] and a default. The mapping uses
linear interpolation with clinical anchors where available.

IMPORTANT: This layer is a useful LOOKUP TABLE, not novel IP. The core IP
of ClinFish is the GROUNDED/DIRECTIONAL/ASSUMED tagging + SMM calibration
pipeline. This module is additive utility.

All mappings are tagged per the epistemic framework:
  GROUNDED    Direct empirical anchor
  DIRECTIONAL Sign/direction supported; magnitude estimated
  ASSUMED     No empirical anchor; use with caution
"""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass
class PolicyConfig:
    """15-dimension sponsor policy configuration.

    All dimensions are floats in [0.0, 1.0] unless otherwise noted.
    """

    # Patient experience
    patient_support_investment: float = 0.5      # 0=none, 1=full coordinators+transport
    digital_health_integration: float = 0.5      # 0=paper CRF, 1=full eDiary+wearable
    site_proximity_strategy: float = 0.5         # 0=academic centers only, 1=community sites

    # Operational
    risk_monitoring_intensity: float = 0.5       # 0=100% SDV, 1=full RBM
    protocol_complexity: float = 0.5             # 0=minimal, 1=highly complex
    amendment_appetite: float = 0.5              # 0=freeze protocol, 1=frequent amendments
    site_count_strategy: float = 0.5             # 0=few sites, 1=many sites

    # Scientific
    enrichment_strategy: float = 0.5             # 0=broad eligibility, 1=narrow biomarker
    adaptive_design: float = 0.0                 # 0=fixed design, 1=fully adaptive
    placebo_ratio: float = 0.5                   # 0=active control, 1=high placebo ratio

    # Commercial
    competitive_urgency: float = 0.5             # 0=no competitors, 1=race to market
    geography_breadth: float = 0.5               # 0=single country, 1=global

    # Safety
    dsmb_oversight: float = 0.5                  # 0=no DSMB, 1=monthly DSMB review
    safety_stopping_conservatism: float = 0.5    # 0=liberal (continue), 1=conservative (stop)

    # Patient centricity
    burden_reduction_priority: float = 0.5       # 0=max burden, 1=DCT/decentralized


def apply_policy(policy: PolicyConfig) -> dict[str, Any]:
    """Translate 15-dimension policy into SimConfig parameter adjustments.

    Returns a dict that can be spread over SimConfig kwargs.
    All intermediate calculations are tagged.
    """
    params: dict[str, Any] = {}

    # patient_support_program: binary threshold
    # [DIRECTIONAL — patient support programs reduce dropout; magnitude ASSUMED]
    params["patient_support_program"] = policy.patient_support_investment >= 0.5

    # enrollment_rate_modifier: affected by site proximity, geography, and urgency
    # Community sites (site_proximity=1) recruit 1.3-1.8x faster than academic-only
    # Source: Tufts CSDD site performance data; magnitude DIRECTIONAL
    site_rate_factor = 1.0 + 0.4 * policy.site_proximity_strategy
    geography_factor = 1.0 + 0.3 * policy.geography_breadth
    urgency_factor = 1.0 + 0.2 * policy.competitive_urgency
    params["enrollment_rate_modifier"] = round(
        site_rate_factor * geography_factor * urgency_factor, 3
    )

    # protocol_burden: complexity + burden_reduction work in opposite directions
    # [DIRECTIONAL — direction grounded; linear combination ASSUMED]
    params["protocol_burden"] = round(
        0.5 + 0.4 * policy.protocol_complexity - 0.3 * policy.burden_reduction_priority, 3
    )
    params["protocol_burden"] = max(0.1, min(1.0, params["protocol_burden"]))

    # protocol_visit_burden: digital reduces burden; decentralized further reduces
    # [DIRECTIONAL]
    params["protocol_visit_burden"] = round(
        0.5
        + 0.3 * policy.protocol_complexity
        - 0.3 * policy.digital_health_integration
        - 0.2 * policy.burden_reduction_priority,
        3,
    )
    params["protocol_visit_burden"] = max(0.1, min(1.0, params["protocol_visit_burden"]))

    # monitoring_active: RBM strategies
    # [GROUNDED: Andersen et al. 2023 Br J Clin Pharmacol — RBM reduces deviations 46%]
    params["monitoring_active"] = policy.risk_monitoring_intensity >= 0.3

    # visits_per_month: burden reduction and digital reduce visit frequency
    # [DIRECTIONAL — direction; specific values ASSUMED]
    base_visits = 2.0
    visits = base_visits * (1.0 + 0.5 * policy.protocol_complexity) * (
        1.0 - 0.4 * policy.burden_reduction_priority
    )
    params["visits_per_month"] = round(max(0.5, min(8.0, visits)), 2)

    # amendment_appetite: higher appetite → more amendments → higher site burden
    # [DIRECTIONAL — higher appetite → more amendments → higher site burden]
    params["amendment_initiation_rate_modifier"] = round(0.5 + 0.8 * policy.amendment_appetite, 3)

    # adaptive_design: adaptive trials can accelerate enrollment
    # [DIRECTIONAL — adaptive designs can accelerate enrollment; 10% magnitude ASSUMED]
    params["adaptive_design_enabled"] = policy.adaptive_design >= 0.5
    params["enrollment_rate_modifier"] = round(
        params["enrollment_rate_modifier"] * (1.0 + 0.10 * policy.adaptive_design), 3
    )

    # enrichment_strategy: narrow eligibility trades speed for retention
    # [DIRECTIONAL — enrichment trades enrollment speed for retention; magnitudes ASSUMED]
    params["enrichment_factor"] = round(policy.enrichment_strategy, 3)
    params["enrollment_rate_modifier"] = round(
        params["enrollment_rate_modifier"] * (1.0 - 0.30 * policy.enrichment_strategy), 3
    )
    params["dropout_rate_modifier"] = round(1.0 - 0.20 * policy.enrichment_strategy, 3)

    # placebo_ratio: more placebo → more lack-of-efficacy dropout
    # [DIRECTIONAL — placebo patients more likely to dropout for efficacy failure; 40% max ASSUMED]
    params["efficacy_dropout_modifier"] = round(1.0 + 0.40 * policy.placebo_ratio, 3)

    # dsmb_oversight: intensive DSMB → LOWER sensitivity threshold (triggers at lower signal level)
    # dsmb_oversight=0 → threshold=0.70 (minimal oversight, barely triggers)
    # dsmb_oversight=1 → threshold=0.20 (monthly DSMB, triggers early)
    # [DIRECTIONAL — direction grounded; linear mapping ASSUMED]
    params["dsmb_sensitivity"] = round(0.70 - 0.50 * policy.dsmb_oversight, 3)

    # safety_stopping_conservatism: conservative sponsors set LOWER safety signal threshold (stop earlier)
    # conservatism=0 → threshold=1.0 (liberal; wait for clinical hold before stopping)
    # conservatism=1 → threshold=0.60 (conservative; stop at first clear signal)
    # [DIRECTIONAL — direction grounded; linear mapping ASSUMED]
    params["safety_stopping_threshold"] = round(1.0 - 0.40 * policy.safety_stopping_conservatism, 3)

    return params


def policy_to_simconfig_description(policy: PolicyConfig) -> str:
    """Return a plain-English description of what the policy implies for the trial.

    Useful for audit trails and frontend display.
    """
    lines: list[str] = []

    # Patient experience
    if policy.patient_support_investment >= 0.7:
        lines.append("Full patient support program (coordinators, transport, reminders).")
    elif policy.patient_support_investment <= 0.3:
        lines.append("Minimal patient support — patients self-manage appointments.")

    if policy.digital_health_integration >= 0.7:
        lines.append("Full eDiary and wearable integration; paper CRF eliminated.")
    elif policy.digital_health_integration <= 0.3:
        lines.append("Paper-based CRF; no digital health tools.")

    if policy.site_proximity_strategy >= 0.7:
        lines.append(
            "Community-site-first strategy: broader geographic reach, faster enrollment."
        )
    elif policy.site_proximity_strategy <= 0.3:
        lines.append("Academic centers only: slower enrollment but high data quality.")

    # Operational
    if policy.risk_monitoring_intensity >= 0.7:
        lines.append(
            "Full risk-based monitoring (RBM); reduced on-site SDV burden for sites."
        )
    elif policy.risk_monitoring_intensity <= 0.3:
        lines.append("100% source data verification; high monitoring burden per site.")

    if policy.protocol_complexity >= 0.7:
        lines.append(
            "Highly complex protocol: many endpoints, strict procedures, elevated dropout risk."
        )
    elif policy.protocol_complexity <= 0.3:
        lines.append("Streamlined protocol design: few endpoints, low procedural burden.")

    if policy.amendment_appetite >= 0.7:
        lines.append(
            "Frequent protocol amendments expected; site re-training overhead factored in."
        )
    elif policy.amendment_appetite <= 0.2:
        lines.append("Protocol freeze policy: no amendments planned post-activation.")

    # Scientific
    if policy.enrichment_strategy >= 0.7:
        lines.append(
            "Biomarker enrichment: narrow eligibility increases responder rate but slows "
            "enrollment."
        )
    elif policy.enrichment_strategy <= 0.3:
        lines.append("Broad eligibility criteria: faster enrollment, more heterogeneous population.")

    if policy.adaptive_design >= 0.5:
        lines.append(
            "Adaptive design elements included (e.g., interim analyses, dose adjustment)."
        )

    # Commercial
    if policy.competitive_urgency >= 0.7:
        lines.append(
            "High competitive urgency: accelerated timeline, enrollment rate boosted."
        )
    elif policy.competitive_urgency <= 0.2:
        lines.append("No competitive pressure; standard enrollment pacing.")

    if policy.geography_breadth >= 0.7:
        lines.append("Global multi-regional trial: many countries, high enrollment rate multiplier.")
    elif policy.geography_breadth <= 0.3:
        lines.append("Single-country or regional trial.")

    # Safety
    if policy.dsmb_oversight >= 0.7:
        lines.append("Frequent DSMB review (monthly or quarterly): highest safety oversight.")
    elif policy.dsmb_oversight <= 0.2:
        lines.append("No independent DSMB; safety oversight via internal review only.")

    if policy.safety_stopping_conservatism >= 0.7:
        lines.append(
            "Conservative stopping rules: early termination likely at first safety signal."
        )
    elif policy.safety_stopping_conservatism <= 0.2:
        lines.append("Liberal stopping criteria; trial designed to complete despite minor signals.")

    # Patient centricity
    if policy.burden_reduction_priority >= 0.7:
        lines.append(
            "Decentralized/hybrid trial elements: home visits, telehealth, reduced site trips."
        )
    elif policy.burden_reduction_priority <= 0.3:
        lines.append("Traditional site-based model: all visits on-site, maximum patient burden.")

    if not lines:
        lines.append(
            "Balanced policy configuration across all 15 dimensions — no extreme settings."
        )

    return " ".join(lines)
