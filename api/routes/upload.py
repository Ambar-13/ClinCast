"""Protocol upload endpoint — parse a trial protocol document into SimulateRequest params."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from clinfish.ingest.protocol import parse_protocol, TrialSpec

router = APIRouter(prefix="/upload", tags=["protocol"])


class ParsedProtocolResponse(BaseModel):
    """Partial SimulateRequest fields extracted from a protocol document.

    Only fields that could be confidently extracted are included.
    The frontend merges these into the current form state.
    """
    title:           str
    document_type:   str = "Protocol"
    confidence:      str            # "high" | "medium" | "low"
    assumed_fields:  list[str]
    params:          dict[str, Any]  # subset of SimulateRequest fields
    field_sources:   dict[str, str] = {}   # field → "explicit"|"inferred"|"default"
    field_reasoning: dict[str, str] = {}   # field → reasoning string
    summary:         str = ""


def _make_llm_client(openai_api_key: str | None):
    """Same priority chain as the swarm service: request key → env OpenAI → env Anthropic → None."""
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


ALL_SIM_FIELDS = [
    "therapeutic_area", "n_patients", "n_sites", "n_rounds",
    "visits_per_month", "visit_duration_hours", "invasive_procedures",
    "ediary_frequency", "monitoring_active", "patient_support_program",
    "randomization_ratio", "blinded", "competitive_pressure",
    "enrollment_rate_modifier",
]

# Sensible fallbacks when a field is missing from the spec
_FIELD_FALLBACKS: dict[str, Any] = {
    "therapeutic_area":        "other",
    "n_patients":              200,
    "n_sites":                 20,
    "n_rounds":                12,
    "visits_per_month":        2.0,
    "visit_duration_hours":    2.0,
    "invasive_procedures":     "blood",
    "ediary_frequency":        "none",
    "monitoring_active":       True,
    "patient_support_program": False,
    "randomization_ratio":     "1:1",
    "blinded":                 True,
    "competitive_pressure":    "none",
    "enrollment_rate_modifier": 1.0,
}

# Mapping from ALL_SIM_FIELDS names to TrialSpec attribute names
_SPEC_ATTR_MAP: dict[str, str] = {
    "n_patients": "n_patients_target",
    "n_sites":    "n_sites_target",
    "n_rounds":   "n_rounds",  # computed below
}


def _spec_to_params(spec: TrialSpec) -> dict[str, Any]:
    """Convert a TrialSpec to a complete SimulateRequest dict with all simulation fields."""
    params: dict[str, Any] = {}

    # therapeutic_area
    params["therapeutic_area"] = spec.therapeutic_area.value

    # n_patients
    params["n_patients"] = getattr(spec, "n_patients_target", None) or _FIELD_FALLBACKS["n_patients"]

    # n_sites
    params["n_sites"] = getattr(spec, "n_sites_target", None) or _FIELD_FALLBACKS["n_sites"]

    # n_rounds — prefer spec.duration_weeks → convert, with spec visit schedule override
    duration_weeks = getattr(spec, "duration_weeks", None)
    if duration_weeks:
        params["n_rounds"] = max(1, round(duration_weeks / 4.33))
    else:
        params["n_rounds"] = _FIELD_FALLBACKS["n_rounds"]

    # visits_per_month — prefer direct field, then derive from visit_schedule
    vpm = getattr(spec, "visits_per_month", None)
    if vpm is not None:
        params["visits_per_month"] = vpm
    elif spec.visit_schedule and spec.visit_schedule.interval_weeks and spec.visit_schedule.interval_weeks > 0:
        params["visits_per_month"] = round(4.33 / spec.visit_schedule.interval_weeks, 2)
    else:
        params["visits_per_month"] = _FIELD_FALLBACKS["visits_per_month"]

    # visit_duration_hours
    vdh = getattr(spec, "visit_duration_hours", None)
    params["visit_duration_hours"] = vdh if vdh is not None else _FIELD_FALLBACKS["visit_duration_hours"]

    # invasive_procedures — prefer direct field, then derive from n_procedures_per_visit
    inv = getattr(spec, "invasive_procedures", None)
    if inv is not None:
        params["invasive_procedures"] = inv
    else:
        n = getattr(spec, "n_procedures_per_visit", 3) or 3
        params["invasive_procedures"] = "biopsy" if n > 4 else "blood"

    # ediary_frequency
    edf = getattr(spec, "ediary_frequency", None)
    params["ediary_frequency"] = edf if edf is not None else _FIELD_FALLBACKS["ediary_frequency"]

    # monitoring_active
    params["monitoring_active"] = bool(getattr(spec, "monitoring_active", _FIELD_FALLBACKS["monitoring_active"]))

    # patient_support_program
    params["patient_support_program"] = bool(getattr(spec, "patient_support_program", _FIELD_FALLBACKS["patient_support_program"]))

    # randomization_ratio
    rr = getattr(spec, "randomization_ratio", None)
    params["randomization_ratio"] = rr if rr is not None else _FIELD_FALLBACKS["randomization_ratio"]

    # blinded
    params["blinded"] = bool(getattr(spec, "blinded", _FIELD_FALLBACKS["blinded"]))

    # competitive_pressure
    cp = getattr(spec, "competitive_pressure", None)
    params["competitive_pressure"] = cp if cp is not None else _FIELD_FALLBACKS["competitive_pressure"]

    # enrollment_rate_modifier
    erm = getattr(spec, "enrollment_rate_modifier", None)
    params["enrollment_rate_modifier"] = erm if erm is not None else _FIELD_FALLBACKS["enrollment_rate_modifier"]

    # Retain legacy fields for backward compat
    params["has_dsmb"]         = spec.has_dsmb
    params["interim_analyses"] = spec.interim_analyses

    return params


@router.post("/protocol", response_model=ParsedProtocolResponse)
async def upload_protocol(
    file:           UploadFile = File(..., description="PDF, Markdown, or text protocol document"),
    use_llm:        bool       = Form(True,  description="Use LLM extraction (recommended)"),
    openai_api_key: Optional[str] = Form(None, description="OpenAI key (overrides env var)"),
) -> ParsedProtocolResponse:
    """Parse an uploaded protocol document and return structured SimulateRequest parameters."""
    suffix = Path(file.filename or "protocol.txt").suffix.lower()
    if suffix not in {".pdf", ".md", ".txt"}:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{suffix}'. Supported: .pdf, .md, .txt"
        )

    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File exceeds 20 MB limit")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        llm_client = _make_llm_client(openai_api_key.strip() if openai_api_key else None) if use_llm else None
        spec: TrialSpec = parse_protocol(tmp_path, llm_client=llm_client)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Protocol parsing failed: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    params = _spec_to_params(spec)

    return ParsedProtocolResponse(
        title=spec.title,
        document_type=spec.document_type,
        confidence=spec.extraction_confidence,
        assumed_fields=spec.assumed_fields,
        params=params,
        field_sources=spec.field_sources,
        field_reasoning=spec.field_reasoning,
        summary=spec.summary,
    )
