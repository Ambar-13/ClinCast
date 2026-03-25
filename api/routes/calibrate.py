from fastapi import APIRouter, HTTPException, BackgroundTasks

from api.schemas.request import CalibrateRequest
from api.schemas.response import CalibrateResponse

router = APIRouter(prefix="/calibrate", tags=["calibration"])


@router.post("", response_model=CalibrateResponse)
def calibrate(req: CalibrateRequest) -> CalibrateResponse:
    """Run SMM calibration for a therapeutic area (CPU-intensive, ~60–300s)."""
    from clincast.core.calibration.smm import run_smm
    from clincast.core.calibration.moments import get_moments
    from clincast.core.engine import SimConfig, run_simulation

    try:
        target = get_moments(req.therapeutic_area)
        bounds = [(0.2, 0.9), (0.2, 0.9)]

        def simulator(params):
            config = SimConfig(
                therapeutic_area=req.therapeutic_area,
                n_patients=300,
                n_sites=15,
                n_rounds=24,
                protocol_burden=params[0],
                protocol_visit_burden=params[1],
                seed=42,
            )
            return run_simulation(config)

        def moment_extractor(trial_outputs):
            rounds = trial_outputs.round_snapshots
            n = trial_outputs.n_patients
            if not rounds:
                return [0.0] * len(target.values)
            r6  = next((r for r in rounds if r.time_months >= 6),  rounds[-1])
            r18 = next((r for r in rounds if r.time_months >= 18), rounds[-1])
            last_active = next((r for r in reversed(rounds) if r.n_enrolled > 0), rounds[-1])
            return [
                r6.n_dropout  / max(n, 1),
                r18.n_dropout / max(n, 1),
                last_active.mean_adherence,
                last_active.visit_compliance_rate,
                last_active.data_quality,
                last_active.ae_reporting_mean,
            ]

        result = run_smm(
            simulator=simulator,
            moment_extractor=moment_extractor,
            target=target,
            bounds=bounds,
            n_lhs=req.n_lhs_samples,
        )

        return CalibrateResponse(
            therapeutic_area=req.therapeutic_area,
            best_params=list(result["best_params"]),
            best_distance=float(result["best_distance"]),
            elapsed_seconds=float(result["elapsed_seconds"]),
            moment_names=list(target.names),
            target_values=[float(v) for v in target.values],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
