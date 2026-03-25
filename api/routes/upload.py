"""Protocol upload endpoint — parse a trial protocol document into SimulateRequest params."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from clincast.ingest.protocol import parse_protocol, TrialSpec

router = APIRouter(prefix="/upload", tags=["protocol"])


class ParsedProtocolResponse(BaseModel):
    """Partial SimulateRequest fields extracted from a protocol document.

    Only fields that could be confidently extracted are included.
    The frontend merges these into the current form state.
    """
    title:          str
    confidence:     str            # "high" | "medium" | "low"
    assumed_fields: list[str]
    params:         dict[str, Any]  # subset of SimulateRequest fields


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


def _spec_to_params(spec: TrialSpec) -> dict[str, Any]:
    """Convert a TrialSpec to a partial SimulateRequest dict."""
    params: dict[str, Any] = {
        "therapeutic_area": spec.therapeutic_area.value,
    }

    if spec.n_patients_target:
        params["n_patients"] = spec.n_patients_target
    if spec.n_sites_target:
        params["n_sites"] = spec.n_sites_target
    if spec.duration_weeks:
        params["n_rounds"] = max(1, round(spec.duration_weeks / 4.33))

    if spec.visit_schedule:
        vs = spec.visit_schedule
        # visits_per_month = 4.33 / interval_weeks (weeks/visit → visits/month)
        if vs.interval_weeks and vs.interval_weeks > 0:
            params["visits_per_month"] = round(4.33 / vs.interval_weeks, 2)

    if spec.n_procedures_per_visit:
        n = spec.n_procedures_per_visit
        if n <= 2:
            params["invasive_procedures"] = "blood"
        elif n <= 4:
            params["invasive_procedures"] = "blood"
        else:
            params["invasive_procedures"] = "biopsy"

    params["has_dsmb"]          = spec.has_dsmb
    params["interim_analyses"]  = spec.interim_analyses
    params["blinded"]           = True  # default; may be overridden by LLM
    params["monitoring_active"] = True  # default

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

    # Merge any extra fields extracted directly by the LLM (visits_per_month, etc.)
    # that bypass the TrialSpec dataclass (they come back via spec.__dict__ raw extras)
    # These are stored on spec if the LLM returned them in the new schema format.
    for attr in ("visits_per_month", "visit_duration_hours", "invasive_procedures",
                 "ediary_frequency", "monitoring_active", "patient_support_program",
                 "randomization_ratio", "blinded", "competitive_pressure"):
        val = getattr(spec, attr, None)
        if val is not None:
            params[attr] = val

    return ParsedProtocolResponse(
        title=spec.title,
        confidence=spec.extraction_confidence,
        assumed_fields=spec.assumed_fields,
        params=params,
    )
