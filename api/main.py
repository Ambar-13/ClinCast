"""ClinCast FastAPI application."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import simulate, presets, inject, upload, calibrate

app = FastAPI(
    title="ClinCast",
    version="0.1.0",
    description=(
        "Clinical trial behavioral simulation engine. "
        "Apache 2.0 — open-source alternative to Intera."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(simulate.router)
app.include_router(presets.router)
app.include_router(inject.router)
app.include_router(upload.router)
app.include_router(calibrate.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}
