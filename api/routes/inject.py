"""Injection scenario endpoint — simulate a social/media disruption event."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal, Optional

from api.schemas.request import SimulateRequest, InjectionEventSchema
from api.schemas.response import SimulateResponse
from api.services.simulation import run_simulation_request

router = APIRouter(prefix="/inject", tags=["injection"])


class InjectionScenarioRequest(BaseModel):
    """Simulate a trial with one or more pre-configured injection events."""
    base_scenario: SimulateRequest
    injection_events: list[InjectionEventSchema] = Field(..., min_length=1)


@router.post("", response_model=SimulateResponse)
def inject_scenario(req: InjectionScenarioRequest) -> SimulateResponse:
    """Run a simulation with adversarial belief injection events."""
    try:
        merged = req.base_scenario.model_copy(
            update={"injection_events": req.injection_events}
        )
        return run_simulation_request(merged)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
