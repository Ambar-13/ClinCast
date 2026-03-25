"""ClinicalTrials.gov v2 API integration.

Fetches structured trial parameters from NCT IDs to auto-populate SimConfig.
Uses the v2 REST API (JSON response, no API key required).

API endpoint: GET https://clinicaltrials.gov/api/v2/studies/{nct_id}
Documentation: https://clinicaltrials.gov/data-api/api

This module maps the AACT/CT.gov data model to ClinCast's SimConfig fields.
Unmapped fields are tagged ASSUMED and logged.

References:
  Anisimov & Fedorov (Stat Med 2007, PMID 17639505): Poisson-Gamma enrollment model
    validated against ClinicalTrials.gov completion data — this API is the calibration source.
  Tufts CSDD 2019: enrollment timeline benchmarks used in SMM calibration.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any

from clincast.ingest.protocol import TherapeuticArea, TrialSpec

logger = logging.getLogger(__name__)

_NCT_V2_BASE = "https://clinicaltrials.gov/api/v2/studies/{nct_id}"


# ─────────────────────────────────────────────────────────────────────────────
# ERRORS
# ─────────────────────────────────────────────────────────────────────────────

class NCTNotFoundError(ValueError):
    """Raised when the NCT ID is not found in ClinicalTrials.gov."""


class NCTAPIError(RuntimeError):
    """Raised when the ClinicalTrials.gov API returns an unexpected error."""


# ─────────────────────────────────────────────────────────────────────────────
# CONDITION → THERAPEUTIC AREA MAPPING
# ─────────────────────────────────────────────────────────────────────────────

_CONDITION_TO_TA: dict[str, list[str]] = {
    "oncology":       ["cancer", "tumor", "carcinoma", "lymphoma", "leukemia", "melanoma"],
    "metabolic":      ["diabetes", "obesity", "metabolic", "nash", "nafld"],
    "cns":            ["schizophrenia", "depression", "bipolar", "alzheimer", "parkinson",
                       "dementia", "anxiety"],
    "alzheimers":     ["alzheimer"],
    "cardiovascular": ["cardiac", "heart", "myocardial", "stroke", "hypertension", "atrial"],
    "rare":           ["orphan", "rare disease"],
}

# Evaluation order matters: more specific areas first
_TA_EVAL_ORDER = ["alzheimers", "oncology", "metabolic", "cns", "cardiovascular", "rare"]


def _map_conditions_to_ta(conditions: list[str]) -> TherapeuticArea:
    """Map a list of condition strings to the most specific TherapeuticArea."""
    combined = " ".join(c.lower() for c in conditions)
    for ta_key in _TA_EVAL_ORDER:
        keywords = _CONDITION_TO_TA[ta_key]
        if any(kw in combined for kw in keywords):
            # alzheimers is not a TherapeuticArea enum value — map to CNS
            if ta_key == "alzheimers":
                return TherapeuticArea.CNS
            return TherapeuticArea(ta_key)
    return TherapeuticArea.OTHER


# ─────────────────────────────────────────────────────────────────────────────
# AGE PARSING
# ─────────────────────────────────────────────────────────────────────────────

def _parse_age(age_str: str) -> int:
    """Parse CT.gov age strings like '18 Years', '65 Years', 'N/A'.

    For 'N/A' or unparseable values:
      - minimum age → 18
      - maximum age → 80  (caller decides which default applies)

    The function itself returns 18 for 'N/A' / None; callers that want 80
    for the maximum should pass the result through their own default logic.
    """
    if not age_str or age_str.strip().upper() in ("N/A", "NA", "NONE", ""):
        return 18

    m = re.search(r"(\d+)", age_str)
    if not m:
        return 18

    value = int(m.group(1))

    # Convert months/weeks to years if unit present
    unit = age_str.lower()
    if "month" in unit:
        value = value // 12
    elif "week" in unit:
        value = value // 52
    elif "day" in unit:
        value = value // 365

    return max(0, value)


# ─────────────────────────────────────────────────────────────────────────────
# DATE UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def _parse_date_to_months(date_str: str) -> int | None:
    """Parse CT.gov date string (YYYY-MM or YYYY-MM-DD) → months since epoch.

    Returns None if unparseable.
    """
    if not date_str:
        return None
    # Accept YYYY-MM or YYYY-MM-DD
    m = re.match(r"(\d{4})-(\d{2})", date_str)
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    return year * 12 + month


def _months_between(start: str, end: str) -> int | None:
    """Return the number of calendar months between two CT.gov date strings."""
    s = _parse_date_to_months(start)
    e = _parse_date_to_months(end)
    if s is None or e is None:
        return None
    diff = e - s
    return max(1, diff)


# ─────────────────────────────────────────────────────────────────────────────
# PHASE PARSING
# ─────────────────────────────────────────────────────────────────────────────

def _parse_phase(phases: list[str]) -> int | None:
    """Extract integer phase from CT.gov phases list like ['PHASE3']."""
    for p in phases:
        m = re.search(r"(\d)", p)
        if m:
            return int(m.group(1))
    return None


# ─────────────────────────────────────────────────────────────────────────────
# NETWORK FETCH
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_nct_id(nct_id: str) -> str:
    """Normalize NCT ID to uppercase with 'NCT' prefix."""
    nct_id = nct_id.strip().upper()
    if not nct_id.startswith("NCT"):
        nct_id = "NCT" + nct_id
    return nct_id


def fetch_nct(nct_id: str) -> dict:
    """Fetch raw JSON from the ClinicalTrials.gov v2 API.

    Args:
        nct_id: NCT identifier (e.g. 'NCT01234567' or '01234567').

    Returns:
        Parsed JSON response as a dict.

    Raises:
        NCTNotFoundError: HTTP 404 — study not in registry.
        NCTAPIError: Any other HTTP or network failure.
    """
    nct_id = _normalize_nct_id(nct_id)
    url = _NCT_V2_BASE.format(nct_id=nct_id)

    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "ClinCast/0.1 (open-source trial simulation; contact via GitHub)",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_bytes = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise NCTNotFoundError(
                f"NCT ID '{nct_id}' was not found in ClinicalTrials.gov registry."
            ) from exc
        raise NCTAPIError(
            f"HTTP {exc.code} from ClinicalTrials.gov for {nct_id}: {exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise NCTAPIError(
            f"Network error fetching {nct_id} from ClinicalTrials.gov: {exc.reason}"
        ) from exc

    try:
        return json.loads(raw_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise NCTAPIError(
            f"Invalid JSON response from ClinicalTrials.gov for {nct_id}"
        ) from exc


# ─────────────────────────────────────────────────────────────────────────────
# MAPPING
# ─────────────────────────────────────────────────────────────────────────────

def nct_to_sim_params(nct_data: dict) -> dict[str, Any]:
    """Map a ClinicalTrials.gov v2 JSON response to SimConfig-compatible parameters.

    Args:
        nct_data: Parsed JSON dict from fetch_nct().

    Returns:
        Dict of SimConfig fields. Keys match TrialSpec field names.
        Fields that were not directly mappable are noted in 'assumed_fields'.

    Raises:
        ValueError: If study_type is OBSERVATIONAL (not a clinical trial).
    """
    ps = nct_data.get("protocolSection", {})
    assumed: list[str] = []
    field_sources: dict[str, str] = {}

    # ── Study type guard ──────────────────────────────────────────────────────
    design_module = ps.get("designModule", {})
    study_type = design_module.get("studyType", "")
    if study_type.upper() == "OBSERVATIONAL":
        raise ValueError(
            "Study type is OBSERVATIONAL — not a clinical trial. "
            "ClinCast simulates interventional trials only."
        )

    params: dict[str, Any] = {}

    # ── Title ─────────────────────────────────────────────────────────────────
    id_module = ps.get("identificationModule", {})
    params["title"] = id_module.get("briefTitle", id_module.get("nctId", "Unknown"))
    field_sources["title"] = "explicit"

    # ── Phase ─────────────────────────────────────────────────────────────────
    phases_raw = design_module.get("phases", [])
    params["phase"] = _parse_phase(phases_raw)
    if params["phase"] is not None:
        field_sources["phase"] = "explicit"
    else:
        assumed.append("phase")
        field_sources["phase"] = "default"

    # ── Enrollment / n_patients ───────────────────────────────────────────────
    enrollment_info = design_module.get("enrollmentInfo", {})
    enrollment_count = enrollment_info.get("count")
    if enrollment_count is not None:
        params["n_patients_target"] = int(enrollment_count)
        field_sources["n_patients_target"] = "explicit"
    else:
        params["n_patients_target"] = 200
        assumed.append("n_patients_target")
        field_sources["n_patients_target"] = "default"

    # ── Sites / n_sites ───────────────────────────────────────────────────────
    contacts_module = ps.get("contactsLocationsModule", {})
    locations = contacts_module.get("locations", [])
    if locations:
        countries = {loc.get("country", "") for loc in locations if loc.get("country")}
        n_countries = len(countries)
        # Heuristic: ~5 sites per country (Tufts CSDD benchmark)
        params["n_sites_target"] = max(1, n_countries * 5)
        field_sources["n_sites_target"] = "inferred"
        logger.debug(
            "[ASSUMED] n_sites_target estimated from %d unique countries × 5", n_countries
        )
        assumed.append("n_sites_target")
    else:
        params["n_sites_target"] = 20
        assumed.append("n_sites_target")
        field_sources["n_sites_target"] = "default"

    # ── Duration / n_rounds ───────────────────────────────────────────────────
    status_module = ps.get("statusModule", {})
    start_date = (status_module.get("startDateStruct") or {}).get("date", "")
    end_date = (status_module.get("primaryCompletionDateStruct") or {}).get("date", "")
    n_rounds = _months_between(start_date, end_date)
    if n_rounds is not None:
        params["duration_weeks"] = n_rounds * 4
        field_sources["duration_weeks"] = "explicit"
    else:
        params["duration_weeks"] = 52
        assumed.append("duration_weeks")
        field_sources["duration_weeks"] = "default"

    # ── Eligibility ───────────────────────────────────────────────────────────
    elig_module = ps.get("eligibilityModule", {})
    min_age_str = elig_module.get("minimumAge", "")
    max_age_str = elig_module.get("maximumAge", "")

    params["min_age"] = _parse_age(min_age_str)
    # For max_age, treat "N/A" / unparseable as 80
    if not max_age_str or max_age_str.strip().upper() in ("N/A", "NA", "NONE", ""):
        params["max_age"] = 80
        assumed.append("max_age")
        field_sources["max_age"] = "default"
    else:
        raw_max = _parse_age(max_age_str)
        params["max_age"] = raw_max if raw_max > 0 else 80
        field_sources["max_age"] = "explicit"

    if min_age_str and min_age_str.strip().upper() not in ("N/A", "NA", "NONE", ""):
        field_sources["min_age"] = "explicit"
    else:
        assumed.append("min_age")
        field_sources["min_age"] = "default"

    # ── Therapeutic area from conditions ─────────────────────────────────────
    conditions_module = ps.get("conditionsModule", {})
    conditions = conditions_module.get("conditions", [])
    if conditions:
        params["therapeutic_area"] = _map_conditions_to_ta(conditions).value
        field_sources["therapeutic_area"] = "inferred"
    else:
        params["therapeutic_area"] = TherapeuticArea.OTHER.value
        assumed.append("therapeutic_area")
        field_sources["therapeutic_area"] = "default"

    # ── Blinding ──────────────────────────────────────────────────────────────
    design_info = design_module.get("designInfo", {})
    masking_info = design_info.get("maskingInfo", {})
    masking = masking_info.get("masking", "").upper()
    if masking in ("TRIPLE", "DOUBLE", "QUADRUPLE"):
        params["blinded"] = True
        field_sources["blinded"] = "explicit"
    elif masking in ("SINGLE",):
        params["blinded"] = True
        field_sources["blinded"] = "explicit"
    elif masking in ("NONE", "OPEN LABEL", ""):
        params["blinded"] = masking not in ("NONE", "OPEN LABEL")
        if masking == "":
            assumed.append("blinded")
            field_sources["blinded"] = "default"
        else:
            field_sources["blinded"] = "explicit"
    else:
        params["blinded"] = True
        assumed.append("blinded")
        field_sources["blinded"] = "default"

    # ── DSMB ──────────────────────────────────────────────────────────────────
    oversight_module = ps.get("oversightModule", {})
    oversight_text = json.dumps(oversight_module).upper()
    has_dsmb = "DSMB" in oversight_text or "SAFETY MONITORING COMMITTEE" in oversight_text
    if not has_dsmb:
        # Also check oversight flag
        has_dsmb = bool(oversight_module.get("oversightHasDmc", False))
    params["has_dsmb"] = has_dsmb
    if oversight_module:
        field_sources["has_dsmb"] = "inferred"
    else:
        assumed.append("has_dsmb")
        field_sources["has_dsmb"] = "default"

    # ── Operational defaults (ASSUMED — no direct CT.gov mapping) ─────────────
    # These are carried forward from protocol.py's TA-based inference defaults
    params["monitoring_active"] = True
    assumed.append("monitoring_active")
    field_sources["monitoring_active"] = "default"

    params["patient_support_program"] = False
    assumed.append("patient_support_program")
    field_sources["patient_support_program"] = "default"

    params["enrollment_rate_modifier"] = 1.0
    assumed.append("enrollment_rate_modifier")
    field_sources["enrollment_rate_modifier"] = "default"

    # ── Summary ───────────────────────────────────────────────────────────────
    desc_module = ps.get("descriptionModule", {})
    brief_summary = desc_module.get("briefSummary", "")
    brief_title = params["title"]
    cond_str = ", ".join(conditions[:3]) if conditions else "unknown condition"
    phase_str = f"Phase {params['phase']}" if params["phase"] else "unspecified phase"
    params["summary"] = (
        f"{phase_str} study: {brief_title}. "
        f"Condition(s): {cond_str}. "
        f"Enrollment target: {params['n_patients_target']} patients."
    )
    if brief_summary:
        # Truncate to a reasonable length
        params["summary"] = brief_summary[:300].strip()

    # ── Extraction metadata ───────────────────────────────────────────────────
    n_key = len(field_sources)
    n_explicit = sum(1 for v in field_sources.values() if v == "explicit")
    n_inferred = sum(1 for v in field_sources.values() if v == "inferred")
    if n_key > 0:
        if n_explicit / n_key > 0.70:
            extraction_confidence = "high"
        elif (n_explicit + n_inferred) / n_key > 0.40:
            extraction_confidence = "medium"
        else:
            extraction_confidence = "low"
    else:
        extraction_confidence = "low"

    params["assumed_fields"] = assumed
    params["field_sources"] = field_sources
    params["extraction_confidence"] = extraction_confidence

    return params


# ─────────────────────────────────────────────────────────────────────────────
# HIGH-LEVEL PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def lookup_nct(nct_id: str, llm_client: Any = None) -> TrialSpec:
    """Fetch trial parameters from ClinicalTrials.gov and return a TrialSpec.

    Args:
        nct_id: NCT identifier (e.g. 'NCT01234567').
        llm_client: Optional OpenAI or Anthropic client. If provided, the
            eligibility criteria text and brief summary are passed through
            the LLM extraction path to enrich visit schedule fields.

    Returns:
        TrialSpec populated from CT.gov data with ASSUMED fields tagged.

    Raises:
        NCTNotFoundError: Study not found.
        NCTAPIError: Network or API failure.
        ValueError: Study is OBSERVATIONAL (not simulatable).
    """
    nct_id = _normalize_nct_id(nct_id)
    raw_data = fetch_nct(nct_id)
    params = nct_to_sim_params(raw_data)

    # Optional LLM enrichment for fields CT.gov doesn't directly provide
    if llm_client is not None:
        try:
            from clincast.ingest.protocol import extract_with_llm

            ps = raw_data.get("protocolSection", {})
            elig_text = ps.get("eligibilityModule", {}).get("eligibilityCriteria", "")
            desc_text = ps.get("descriptionModule", {}).get("briefSummary", "")
            conditions = ps.get("conditionsModule", {}).get("conditions", [])
            combined_text = "\n".join([
                f"Title: {params.get('title', '')}",
                f"Conditions: {', '.join(conditions)}",
                f"Description: {desc_text[:2000]}",
                f"Eligibility: {elig_text[:3000]}",
            ])
            llm_raw = extract_with_llm(combined_text, llm_client)
            # Merge LLM-extracted fields without overwriting explicitly mapped ones
            llm_fields = [
                "visits_per_month", "visit_duration_hours",
                "invasive_procedures", "ediary_frequency",
                "competitive_pressure", "randomization_ratio",
            ]
            for field in llm_fields:
                if llm_raw.get(field) is not None:
                    params[field] = llm_raw[field]
                    # Remove from assumed if LLM provided it
                    if field in params.get("assumed_fields", []):
                        params["assumed_fields"].remove(field)
        except Exception as exc:
            logger.warning("[lookup_nct] LLM enrichment failed (falling back): %s", exc)

    return TrialSpec(
        title=params.get("title", nct_id),
        therapeutic_area=TherapeuticArea(params.get("therapeutic_area", "other")),
        phase=params.get("phase"),
        n_patients_target=params.get("n_patients_target", 200),
        n_sites_target=params.get("n_sites_target", 20),
        duration_weeks=params.get("duration_weeks", 52),
        min_age=params.get("min_age", 18),
        max_age=params.get("max_age", 80),
        visits_per_month=params.get("visits_per_month"),
        visit_duration_hours=params.get("visit_duration_hours"),
        invasive_procedures=params.get("invasive_procedures"),
        ediary_frequency=params.get("ediary_frequency"),
        monitoring_active=params.get("monitoring_active", True),
        patient_support_program=params.get("patient_support_program", False),
        blinded=params.get("blinded", True),
        enrollment_rate_modifier=params.get("enrollment_rate_modifier"),
        has_dsmb=params.get("has_dsmb", True),
        extraction_confidence=params.get("extraction_confidence", "low"),
        assumed_fields=params.get("assumed_fields", []),
        field_sources=params.get("field_sources", {}),
        source_file=f"clinicaltrials.gov:{nct_id}",
        summary=params.get("summary", ""),
    )
