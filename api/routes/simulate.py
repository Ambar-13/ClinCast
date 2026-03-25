import traceback

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from api.schemas.request import SimulateRequest, CompareRequest
from api.schemas.response import SimulateResponse, CompareResponse
from api.services.simulation import run_simulation_request

router = APIRouter(prefix="/simulate", tags=["simulation"])


@router.post("", response_model=SimulateResponse)
async def simulate(req: SimulateRequest) -> SimulateResponse:
    try:
        return await run_in_threadpool(run_simulation_request, req)
    except Exception as exc:
        print(f"[simulate] ERROR: {exc}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/compare", response_model=CompareResponse)
async def compare(req: CompareRequest) -> CompareResponse:
    try:
        a = await run_in_threadpool(run_simulation_request, req.scenario_a)
        b = await run_in_threadpool(run_simulation_request, req.scenario_b)
    except Exception as exc:
        print(f"[compare] ERROR: {exc}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    def _last_val(sim: SimulateResponse, key: str) -> float:
        rs = sim.round_snapshots
        return getattr(rs[-1], key, 0.0) if rs else 0.0

    delta = {
        "dropout_pct":      (a.round_snapshots[-1].n_dropout / max(a.n_patients, 1)
                              - b.round_snapshots[-1].n_dropout / max(b.n_patients, 1))
                            if a.round_snapshots and b.round_snapshots else 0.0,
        "mean_adherence":   _last_val(a, "mean_adherence")    - _last_val(b, "mean_adherence"),
        "data_quality":     _last_val(a, "data_quality")      - _last_val(b, "data_quality"),
        "safety_signal":    _last_val(a, "safety_signal")     - _last_val(b, "safety_signal"),
        "site_burden":      _last_val(a, "site_burden")       - _last_val(b, "site_burden"),
    }
    return CompareResponse(scenario_a=a, scenario_b=b, delta=delta)


@router.get("/nct/{nct_id}")
async def lookup_nct_id(
    nct_id: str,
    use_llm: bool = False,
):
    """Fetch trial parameters from ClinicalTrials.gov v2 API by NCT ID.

    Returns TrialSpec fields as a JSON dict that the frontend can use to
    pre-populate the simulation config form.
    """
    from clincast.ingest.nct import lookup_nct, NCTNotFoundError, NCTAPIError
    try:
        spec = lookup_nct(nct_id)
        normalized = nct_id.strip().upper()
        if not normalized.startswith("NCT"):
            normalized = "NCT" + normalized
        return {
            "nct_id": normalized,
            "title": spec.title,
            "therapeutic_area": spec.therapeutic_area.value,
            "phase": spec.phase,
            "n_patients": spec.n_patients_target,
            "n_sites": spec.n_sites_target,
            "n_rounds": spec.duration_weeks // 4,
            "visits_per_month": spec.visits_per_month,
            "visit_duration_hours": spec.visit_duration_hours,
            "invasive_procedures": spec.invasive_procedures,
            "ediary_frequency": spec.ediary_frequency,
            "monitoring_active": spec.monitoring_active,
            "patient_support_program": spec.patient_support_program,
            "blinded": spec.blinded,
            "has_dsmb": spec.has_dsmb,
            "extraction_confidence": spec.extraction_confidence,
            "assumed_fields": spec.assumed_fields,
            "summary": spec.summary,
        }
    except NCTNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except NCTAPIError as e:
        raise HTTPException(status_code=502, detail=f"ClinicalTrials.gov API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/policy")
async def apply_policy_endpoint(policy_config: dict):
    """Translate sponsor policy dimensions to SimConfig parameters."""
    from clincast.ingest.policy import PolicyConfig, apply_policy
    try:
        policy = PolicyConfig(
            **{
                k: v
                for k, v in policy_config.items()
                if k in PolicyConfig.__dataclass_fields__
            }
        )
        params = apply_policy(policy)
        return {"params": params, "policy": policy_config}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
