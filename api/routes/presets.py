from fastapi import APIRouter, HTTPException

from api.schemas.response import PresetResponse
from api.services.evidence import list_presets, get_preset_metadata, get_evidence_summary

router = APIRouter(prefix="/presets", tags=["presets"])


@router.get("", response_model=list[PresetResponse])
def list_all_presets() -> list[PresetResponse]:
    return list_presets()


@router.get("/{therapeutic_area}", response_model=PresetResponse)
def get_preset(therapeutic_area: str) -> PresetResponse:
    try:
        return get_preset_metadata(therapeutic_area)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown therapeutic area: {therapeutic_area}")


@router.get("/{therapeutic_area}/evidence")
def get_evidence(therapeutic_area: str) -> dict:
    try:
        return get_evidence_summary(therapeutic_area)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
