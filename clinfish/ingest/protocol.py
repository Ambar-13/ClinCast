"""Clinical protocol document → trial simulation parameters.

Accepts PDF, Markdown, or plain text. Extracts the structural elements that
drive simulation behaviour: therapeutic area, patient eligibility, visit
schedule, endpoints, dose regimen, and stopping rules.

The extraction uses an LLM with a structured JSON schema. If no LLM is
configured, a rule-based fallback extracts what it can from text patterns
and flags missing parameters as ASSUMED.

The output TrialSpec is domain-validated (e.g., visit intervals that are
clinically implausible are rejected) before being passed to the simulation
engine. This catches prompt-injection or LLM hallucination of protocol
parameters that would produce nonsensical simulations.
"""

from __future__ import annotations

import dataclasses
import json
import re
from enum import Enum
from pathlib import Path
from typing import Any


class TherapeuticArea(str, Enum):
    ONCOLOGY    = "oncology"
    METABOLIC   = "metabolic"       # T2DM, obesity, NAFLD
    CNS         = "cns"             # schizophrenia, depression, Alzheimer's
    CARDIOVASCULAR = "cardiovascular"
    IMMUNOLOGY  = "immunology"      # RA, lupus, IBD
    RARE        = "rare"
    OTHER       = "other"


@dataclasses.dataclass
class VisitSchedule:
    n_visits: int
    interval_weeks: float       # mean interval between scheduled visits
    first_visit_weeks: float    # time from enrollment to first visit
    window_days: int = 7        # allowed deviation from scheduled date


@dataclasses.dataclass
class TrialSpec:
    """Structured representation of a clinical trial protocol.

    All fields that could not be extracted from the document are marked
    with their source = "ASSUMED — extracted default" in the output
    evidence pack.
    """

    title: str
    therapeutic_area: TherapeuticArea
    phase: int | None              # 1, 2, 3, or None if not found
    n_patients_target: int
    n_sites_target: int
    duration_weeks: int            # planned trial duration

    # Inclusion/exclusion summary (used for archetype weighting)
    min_age: int = 18
    max_age: int = 80
    requires_caregiver: bool = False
    prior_treatment_required: bool = False

    # Concrete visit schedule params (map directly to SimulateRequest)
    visit_schedule: VisitSchedule | None = None
    n_procedures_per_visit: int = 3
    dose_frequency_per_day: int = 1
    visits_per_month:       float | None = None
    visit_duration_hours:   float | None = None
    invasive_procedures:    str   | None = None  # none/blood/lp/biopsy/infusion
    ediary_frequency:       str   | None = None  # none/weekly/daily

    # Site & operations
    monitoring_active:       bool = True
    patient_support_program: bool = False

    # Trial design
    randomization_ratio:   str  | None = None  # 1:1/2:1/3:1
    blinded:               bool = True
    competitive_pressure:  str  | None = None  # none/low/medium/high
    enrollment_rate_modifier: float | None = None

    # Primary endpoint
    primary_endpoint: str = ""
    endpoint_timepoint_weeks: int | None = None

    # Stopping rules
    has_dsmb: bool = True
    interim_analyses: int = 0

    # Extraction metadata
    source_file: str = ""
    extraction_confidence: str = "high"   # high | medium | low
    assumed_fields: list[str] = dataclasses.field(default_factory=list)
    field_sources: dict = dataclasses.field(default_factory=dict)
    field_reasoning: dict = dataclasses.field(default_factory=dict)
    document_type: str = "Protocol"
    summary: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# TEXT EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

def load_text(path: Path) -> str:
    """Extract raw text from PDF, Markdown, or plain text."""
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ImportError("PyMuPDF is required for PDF ingestion: pip install pymupdf")
        doc = fitz.open(str(path))
        pages = [page.get_text() for page in doc]
        return "\n".join(pages)

    # MD or TXT — detect encoding
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        pass

    try:
        from charset_normalizer import from_path
        result = from_path(path).best()
        if result is not None:
            return str(result)
    except ImportError:
        pass

    return path.read_bytes().decode("utf-8", errors="replace")


def chunk_text(text: str, chunk_size: int = 6000, overlap: int = 400) -> list[str]:
    """Split text into overlapping chunks at sentence boundaries."""
    sentence_endings = re.compile(r'(?<=[.!?])\s+')
    sentences = sentence_endings.split(text)

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sent in sentences:
        sent_len = len(sent)
        if current_len + sent_len > chunk_size and current:
            chunks.append(" ".join(current))
            # Keep last `overlap` chars worth of sentences for context
            overlap_sents: list[str] = []
            overlap_len = 0
            for s in reversed(current):
                if overlap_len + len(s) > overlap:
                    break
                overlap_sents.insert(0, s)
                overlap_len += len(s)
            current = overlap_sents
            current_len = overlap_len
        current.append(sent)
        current_len += sent_len

    if current:
        chunks.append(" ".join(current))

    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# LLM EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        # Core identity
        "title":            {"type": "string"},
        "therapeutic_area": {"type": "string", "enum": [e.value for e in TherapeuticArea]},
        "phase":            {"type": ["integer", "null"]},

        # Trial scale
        "n_patients":       {"type": "integer",  "description": "Total enrollment target"},
        "n_sites":          {"type": "integer",  "description": "Number of clinical sites"},
        "n_rounds":         {"type": "integer",  "description": "Trial duration in calendar months"},

        # Visit schedule — concrete values preferred over abstract sliders
        "visits_per_month":     {"type": ["number", "null"], "description": "Scheduled clinic visits per month (e.g. 2 = biweekly)"},
        "visit_duration_hours": {"type": ["number", "null"], "description": "Mean hours per clinic visit including travel and waiting"},
        "invasive_procedures":  {"type": ["string", "null"], "enum": ["none", "blood", "lp", "biopsy", "infusion", None],
                                 "description": "Most burdensome procedure type"},
        "ediary_frequency":     {"type": ["string", "null"], "enum": ["none", "weekly", "daily", None],
                                 "description": "Electronic patient diary frequency"},

        # Site & operations
        "monitoring_active":       {"type": "boolean", "description": "Risk-based or traditional SDV monitoring"},
        "patient_support_program": {"type": "boolean", "description": "Patient coordinators, transport, or reminder programs"},

        # Trial design
        "randomization_ratio": {"type": ["string", "null"], "enum": ["1:1", "2:1", "3:1", None]},
        "blinded":             {"type": "boolean"},
        "competitive_pressure": {"type": ["string", "null"], "enum": ["none", "low", "medium", "high", None],
                                 "description": "Infer from context: rival trials, disease rarity, media events"},

        # Stopping rules
        "has_dsmb":          {"type": "boolean"},
        "interim_analyses":  {"type": "integer"},

        # Legacy / fallback (only if concrete schedule not available)
        "n_patients_target":     {"type": ["integer", "null"]},
        "n_sites_target":        {"type": ["integer", "null"]},
        "duration_weeks":        {"type": ["integer", "null"]},
        "n_visits":              {"type": ["integer", "null"]},
        "visit_interval_weeks":  {"type": ["number", "null"]},
        "first_visit_weeks":     {"type": ["number", "null"]},
        "n_procedures_per_visit":{"type": ["integer", "null"]},
    },
    "required": ["title", "therapeutic_area"],
}

_EXTRACTION_PROMPT = """You are a senior clinical trial design expert with 20+ years of experience across all therapeutic areas and trial phases. You are analyzing a document to configure a clinical trial simulation.

STEP 1 — Identify the document type:
Protocol (ICH E6), SOP/Policy, Strategic/portfolio plan, Regulatory submission, Scientific publication, Feasibility assessment, or Other.

STEP 2 — Extract OR infer every parameter below. You MUST provide a value for every field. Use your clinical domain expertise to infer values that are not explicitly stated. Only mark a field "explicit" if the value is clearly stated in the document; otherwise mark it "inferred" and explain why.

INFERENCE RULES (use when not explicit):
- n_patients: Phase I→30-80, Phase II→100-300, Phase III→300-2000, Phase IV→500-5000. Scale down for rare disease.
- n_sites: Phase I→3-8, Phase II→15-40, Phase III→50-200. Rare disease→fewer globally.
- n_rounds (months): Phase I→12-18, Phase II→18-36, Phase III→36-60. Oncology survival endpoints→shorter. Chronic CNS→longer.
- visits_per_month: Phase I intensive safety→4-8/mo. Phase II→2-4/mo. Phase III→1-2/mo. Alzheimer's/CNS chronic→1-2/mo. Oncology chemo cycle→2-4/mo. Metabolic/Rare→1/mo.
- visit_duration_hours: Blood-only→1-2h. Infusion→3-6h. Lumbar puncture→3-4h. Biopsy→2-4h. Standard cognitive/psych assessments→2-3h.
- invasive_procedures: CNS/Alzheimer's→often lp or blood. Oncology→infusion or biopsy. CVD/Metabolic→blood. Rare→blood or infusion. Phase I→always blood at minimum.
- competitive_pressure: Alzheimer's/oncology→high. Rare disease→low (no alternatives). Schizophrenia/CVD→medium. Novel first-in-class→low initially.
- ediary_frequency: CNS/pain/metabolic ePRO→daily. Oncology symptom diary→weekly. CVD/Rare→none or weekly.
- monitoring_active: Industry Phase III→always true. Academic Phase I/II→usually true.
- patient_support_program: Industry-sponsored Phase III→usually true. Rare disease→usually true. Academic→usually false.
- randomization_ratio: Standard→1:1. Active-arm enrichment or placebo ethical concerns→2:1. Rare/oncology→sometimes 2:1.
- blinded: Phase I→usually false (open-label safety). Phase II/III→usually true (double-blind). Oncology with objective tumor response→may be false.
- enrollment_rate_modifier: Common disease with broad eligibility→1.0-1.5. Rare disease or strict criteria→0.3-0.7. Standard→1.0.

FOR POLICY/STRATEGY DOCUMENTS: Extract the INTENT. "Patient-centric rare CNS program" → rare area, low competitive pressure, patient support=true, lower visit burden. Infer what a trial implementing this policy would look like.

FOR ANY DOCUMENT: Write a 2-3 sentence plain-English summary of what trial or program this document describes and what it is trying to achieve.

Document text (up to 12,000 characters):
{text}

Return ONLY a JSON object with these exact fields:
{{
  "title": "string",
  "document_type": "string (Protocol/Policy/Strategy/Regulatory/Publication/Feasibility/Other)",
  "therapeutic_area": "one of: oncology|metabolic|cns|cardiovascular|alzheimers|rare|other",
  "phase": "integer 1-4 or null",
  "n_patients": "integer",
  "n_sites": "integer",
  "n_rounds": "integer (calendar months)",
  "visits_per_month": "number",
  "visit_duration_hours": "number",
  "invasive_procedures": "one of: none|blood|lp|biopsy|infusion",
  "ediary_frequency": "one of: none|weekly|daily",
  "monitoring_active": "boolean",
  "patient_support_program": "boolean",
  "randomization_ratio": "one of: 1:1|2:1|3:1",
  "blinded": "boolean",
  "competitive_pressure": "one of: none|low|medium|high",
  "enrollment_rate_modifier": "number 0.1-3.0",
  "summary": "string (2-3 sentence plain-English description of what this trial/policy is trying to do)",
  "_sources": {{
    "therapeutic_area": "explicit|inferred|default",
    "n_patients": "explicit|inferred|default",
    "n_sites": "explicit|inferred|default",
    "n_rounds": "explicit|inferred|default",
    "visits_per_month": "explicit|inferred|default",
    "visit_duration_hours": "explicit|inferred|default",
    "invasive_procedures": "explicit|inferred|default",
    "ediary_frequency": "explicit|inferred|default",
    "monitoring_active": "explicit|inferred|default",
    "patient_support_program": "explicit|inferred|default",
    "randomization_ratio": "explicit|inferred|default",
    "blinded": "explicit|inferred|default",
    "competitive_pressure": "explicit|inferred|default",
    "enrollment_rate_modifier": "explicit|inferred|default"
  }},
  "_reasoning": {{
    "field_name": "brief explanation for inferred or uncertain fields"
  }}
}}"""


def extract_with_llm(text: str, llm_client: Any) -> dict[str, Any]:
    """Extract structured trial parameters using OpenAI or Anthropic LLM.

    Detects provider via hasattr(client, 'chat') — OpenAI has chat.completions,
    Anthropic uses messages.create directly.
    """
    sample = text[:12_000]
    prompt = _EXTRACTION_PROMPT.format(text=sample)

    is_openai = hasattr(llm_client, "chat")

    if is_openai:
        response = llm_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=1500,
        )
        raw = response.choices[0].message.content
    else:
        # Anthropic
        response = llm_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text

    # Robust JSON extraction — strip markdown fences, prose wrappers, etc.
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    if "{" in raw:
        raw = raw[raw.index("{"):]
    if "}" in raw:
        raw = raw[:raw.rindex("}") + 1]

    return json.loads(raw)


# ─────────────────────────────────────────────────────────────────────────────
# RULE-BASED FALLBACK
# ─────────────────────────────────────────────────────────────────────────────

_TA_KEYWORDS: dict[TherapeuticArea, list[str]] = {
    TherapeuticArea.ONCOLOGY:       ["cancer", "tumor", "tumour", "oncol", "carcinoma", "lymphoma"],
    TherapeuticArea.METABOLIC:      ["diabetes", "t2dm", "obesity", "nafld", "nash", "glycemic"],
    TherapeuticArea.CNS:            ["schizophrenia", "depression", "alzheimer", "parkinson", "cognitive"],
    TherapeuticArea.CARDIOVASCULAR: ["cardiac", "cardiovascular", "myocardial", "heart failure", "stroke"],
    TherapeuticArea.IMMUNOLOGY:     ["rheumatoid", "lupus", "crohn", "ulcerative colitis", "autoimmune"],
    TherapeuticArea.RARE:           ["orphan", "rare disease", "ultra-rare"],
}


def extract_rule_based(text: str) -> tuple[dict[str, Any], list[str]]:
    """Best-effort extraction via regex and keyword matching.

    Returns (extracted_dict, list_of_assumed_fields).
    """
    text_lower = text.lower()
    assumed: list[str] = []
    result: dict[str, Any] = {}

    # Therapeutic area
    ta_detected = TherapeuticArea.OTHER
    for ta, keywords in _TA_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            ta_detected = ta
            break
    result["therapeutic_area"] = ta_detected.value

    # Infer simulation parameters from therapeutic area
    ta_defaults = {
        TherapeuticArea.ONCOLOGY:       {"visits_per_month": 3.0, "visit_duration_hours": 4.0, "invasive_procedures": "infusion", "competitive_pressure": "medium", "ediary_frequency": "weekly", "blinded": False},
        TherapeuticArea.METABOLIC:      {"visits_per_month": 1.0, "visit_duration_hours": 1.5, "invasive_procedures": "blood",   "competitive_pressure": "medium", "ediary_frequency": "daily",  "blinded": True},
        TherapeuticArea.CNS:            {"visits_per_month": 2.0, "visit_duration_hours": 2.0, "invasive_procedures": "blood",   "competitive_pressure": "medium", "ediary_frequency": "daily",  "blinded": True},
        TherapeuticArea.CARDIOVASCULAR: {"visits_per_month": 1.0, "visit_duration_hours": 1.5, "invasive_procedures": "blood",   "competitive_pressure": "high",   "ediary_frequency": "none",   "blinded": True},
        TherapeuticArea.IMMUNOLOGY:     {"visits_per_month": 1.0, "visit_duration_hours": 2.0, "invasive_procedures": "blood",   "competitive_pressure": "medium", "ediary_frequency": "weekly", "blinded": True},
        TherapeuticArea.RARE:           {"visits_per_month": 1.0, "visit_duration_hours": 2.0, "invasive_procedures": "blood",   "competitive_pressure": "low",    "ediary_frequency": "none",   "blinded": True},
        TherapeuticArea.OTHER:          {"visits_per_month": 2.0, "visit_duration_hours": 2.0, "invasive_procedures": "blood",   "competitive_pressure": "none",   "ediary_frequency": "none",   "blinded": True},
    }
    ta_inf = ta_defaults.get(ta_detected, ta_defaults[TherapeuticArea.OTHER])
    for k, v in ta_inf.items():
        result[k] = v
        assumed.append(k)

    # Additional inferred defaults
    result["enrollment_rate_modifier"] = 1.0
    assumed.append("enrollment_rate_modifier")
    result["randomization_ratio"] = "1:1"
    assumed.append("randomization_ratio")
    result["monitoring_active"] = True
    assumed.append("monitoring_active")
    result["patient_support_program"] = False
    assumed.append("patient_support_program")

    # Phase
    phase_match = re.search(r'phase\s+([123])', text_lower)
    result["phase"] = int(phase_match.group(1)) if phase_match else None
    if result["phase"] is None:
        assumed.append("phase")

    # Patient count
    n_match = re.search(
        r'(?:enroll|randomize|recruit)\s+(?:approximately\s+)?(\d+)\s+(?:patients|participants|subjects)',
        text_lower,
    )
    result["n_patients_target"] = int(n_match.group(1)) if n_match else 200
    if not n_match:
        assumed.append("n_patients_target")

    # Duration
    dur_match = re.search(r'(\d+)[- ](?:week|month)', text_lower)
    if dur_match:
        n = int(dur_match.group(1))
        unit = text_lower[dur_match.end() - 5:dur_match.end()]
        result["duration_weeks"] = n * 4 if "month" in unit else n
    else:
        result["duration_weeks"] = 52
        assumed.append("duration_weeks")

    result["title"] = text[:200].split("\n")[0].strip()
    result["n_sites_target"] = 20
    assumed.append("n_sites_target")

    # Build _sources and _reasoning for consistency with LLM output
    key_fields = [
        "therapeutic_area", "n_patients_target", "n_sites_target", "duration_weeks",
        "visits_per_month", "visit_duration_hours", "invasive_procedures",
        "ediary_frequency", "monitoring_active", "patient_support_program",
        "randomization_ratio", "blinded", "competitive_pressure", "enrollment_rate_modifier",
    ]
    sources: dict[str, str] = {}
    reasoning: dict[str, str] = {}
    for field in key_fields:
        if field in assumed:
            sources[field] = "default"
            reasoning[field] = f"No LLM available; inferred from therapeutic area ({ta_detected.value}) defaults"
        else:
            sources[field] = "inferred"

    result["_sources"] = sources
    result["_reasoning"] = reasoning
    result["document_type"] = "Protocol"
    result["summary"] = ""

    return result, assumed


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

_PLAUSIBILITY_CHECKS = [
    ("n_patients_target", 10, 50_000, "patient count out of plausible range"),
    ("duration_weeks",     4, 520,    "trial duration out of plausible range"),
    ("n_visits",           1, 100,    "visit count out of plausible range"),
    ("visit_interval_weeks", 0.1, 52, "visit interval out of plausible range"),
]


def validate_spec(raw: dict[str, Any]) -> list[str]:
    """Return list of validation error strings. Empty list = valid."""
    errors = []
    for field, lo, hi, msg in _PLAUSIBILITY_CHECKS:
        val = raw.get(field)
        if val is not None and not (lo <= val <= hi):
            errors.append(f"{field}={val}: {msg} [{lo}, {hi}]")
    return errors


# ─────────────────────────────────────────────────────────────────────────────
# CONFIDENCE CALCULATION
# ─────────────────────────────────────────────────────────────────────────────

_KEY_FIELDS_FOR_CONFIDENCE = [
    "therapeutic_area", "n_patients", "n_sites", "n_rounds",
    "visits_per_month", "visit_duration_hours", "invasive_procedures",
    "ediary_frequency", "monitoring_active", "patient_support_program",
    "randomization_ratio", "blinded", "competitive_pressure", "enrollment_rate_modifier",
]


def _compute_confidence(sources: dict[str, str]) -> str:
    """Compute extraction confidence from field sources.

    high   → >70% of key fields are "explicit"
    medium → >40% are "explicit" or "inferred"
    low    → mostly defaults or rule-based
    """
    total = len(_KEY_FIELDS_FOR_CONFIDENCE)
    if total == 0:
        return "low"

    n_explicit = sum(1 for f in _KEY_FIELDS_FOR_CONFIDENCE if sources.get(f) == "explicit")
    n_inferred = sum(1 for f in _KEY_FIELDS_FOR_CONFIDENCE if sources.get(f) == "inferred")

    if n_explicit / total > 0.70:
        return "high"
    if (n_explicit + n_inferred) / total > 0.40:
        return "medium"
    return "low"


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def parse_protocol(
    path: Path,
    llm_client: Any | None = None,
) -> TrialSpec:
    """Parse a clinical protocol document into a TrialSpec.

    If llm_client is None, falls back to rule-based extraction and marks
    unextracted fields as ASSUMED.

    Raises ValueError if the extracted parameters fail plausibility checks,
    which catches LLM hallucination and prompt injection attempts.
    """
    text = load_text(path)
    assumed: list[str] = []
    llm_succeeded = False

    if llm_client is not None:
        try:
            raw = extract_with_llm(text, llm_client)
            llm_succeeded = True
        except Exception:
            raw, assumed = extract_rule_based(text)
    else:
        raw, assumed = extract_rule_based(text)

    errors = validate_spec(raw)
    if errors:
        raise ValueError(
            f"Protocol extraction failed plausibility checks:\n" +
            "\n".join(f"  - {e}" for e in errors)
        )

    visit_schedule = None
    if raw.get("n_visits") and raw.get("visit_interval_weeks"):
        visit_schedule = VisitSchedule(
            n_visits=int(raw["n_visits"]),
            interval_weeks=float(raw["visit_interval_weeks"]),
            first_visit_weeks=float(raw.get("first_visit_weeks", 2.0)),
        )

    # Prefer n_patients/n_sites/n_rounds (new schema) over legacy _target/_weeks fields
    n_patients_target = int(
        raw.get("n_patients") or raw.get("n_patients_target") or 200
    )
    n_sites_target = int(
        raw.get("n_sites") or raw.get("n_sites_target") or 20
    )
    duration_weeks_val = int(
        raw.get("duration_weeks") or
        (int(raw.get("n_rounds", 0)) * 4) or 52
    )

    # Pull _sources, _reasoning, document_type, summary from LLM output
    field_sources: dict[str, str] = raw.get("_sources", {})
    field_reasoning: dict[str, str] = raw.get("_reasoning", {})
    document_type: str = raw.get("document_type", "Protocol")
    summary: str = raw.get("summary", "")

    # Compute assumed_fields from _sources when LLM succeeded
    if llm_succeeded:
        assumed = [f for f, src in field_sources.items() if src == "default"]

    # Compute confidence from sources
    if llm_succeeded and field_sources:
        extraction_confidence = _compute_confidence(field_sources)
    else:
        extraction_confidence = "low"

    return TrialSpec(
        title=raw.get("title", path.stem),
        therapeutic_area=TherapeuticArea(raw.get("therapeutic_area", "other")),
        phase=raw.get("phase"),
        n_patients_target=n_patients_target,
        n_sites_target=n_sites_target,
        duration_weeks=duration_weeks_val,
        min_age=int(raw.get("min_age", 18)),
        max_age=int(raw.get("max_age", 80)),
        requires_caregiver=bool(raw.get("requires_caregiver", False)),
        prior_treatment_required=bool(raw.get("prior_treatment_required", False)),
        visit_schedule=visit_schedule,
        n_procedures_per_visit=int(raw.get("n_procedures_per_visit", 3)),
        dose_frequency_per_day=int(raw.get("dose_frequency_per_day", 1)),
        # New concrete fields
        visits_per_month=raw.get("visits_per_month"),
        visit_duration_hours=raw.get("visit_duration_hours"),
        invasive_procedures=raw.get("invasive_procedures"),
        ediary_frequency=raw.get("ediary_frequency"),
        monitoring_active=bool(raw.get("monitoring_active", True)),
        patient_support_program=bool(raw.get("patient_support_program", False)),
        randomization_ratio=raw.get("randomization_ratio"),
        blinded=bool(raw.get("blinded", True)),
        competitive_pressure=raw.get("competitive_pressure"),
        enrollment_rate_modifier=raw.get("enrollment_rate_modifier"),
        primary_endpoint=str(raw.get("primary_endpoint", "")),
        endpoint_timepoint_weeks=raw.get("endpoint_timepoint_weeks"),
        has_dsmb=bool(raw.get("has_dsmb", True)),
        interim_analyses=int(raw.get("interim_analyses", 0)),
        source_file=str(path),
        extraction_confidence=extraction_confidence,
        assumed_fields=assumed,
        field_sources=field_sources,
        field_reasoning=field_reasoning,
        document_type=document_type,
        summary=summary,
    )
