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
