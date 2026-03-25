"""SMM calibration unit tests.

Tests the calibration machinery without running a full LHS grid
(which would take ~60s). Uses a minimal 20-sample LHS to verify
the pipeline runs end-to-end and returns plausible outputs.
"""

import numpy as np
import pytest

from clinfish.core.calibration.smm import (
    TargetMoments,
    SimulatedMoments,
    MLPSurrogate,
    latin_hypercube_sample,
    run_smm,
)
from clinfish.core.calibration.moments import (
    cns_moments,
    cardiovascular_moments,
    oncology_moments,
    metabolic_moments,
    alzheimers_moments,
    get_moments,
)


# ── TargetMoments ─────────────────────────────────────────────────────────────

def test_target_moments_weighting_matrix():
    m = cns_moments()
    W = m.weighting_matrix()
    assert W.shape == (6, 6)
    # Diagonal should be 1/SE²
    for i, se in enumerate(m.ses):
        assert abs(W[i, i] - 1.0 / se**2) < 1e-6
    # Off-diagonal should be zero
    mask = ~np.eye(6, dtype=bool)
    assert np.all(W[mask] == 0.0)


def test_all_moment_constructors_run():
    for fn in [cns_moments, cardiovascular_moments, oncology_moments,
               metabolic_moments, alzheimers_moments]:
        m = fn()
        assert len(m.values) == len(m.ses) == len(m.names) == 6
        assert np.all(m.ses > 0)
        assert np.all((m.values >= 0) & (m.values <= 1))


def test_get_moments_fallback():
    m = get_moments("unknown_ta")
    assert m is not None
    assert len(m.values) == 6


# ── SimulatedMoments ──────────────────────────────────────────────────────────

def test_smm_distance_zero_at_target():
    target = cns_moments()
    sim = SimulatedMoments(
        values=target.values.copy(),
        parameter_vector=np.array([0.5, 0.5]),
    )
    assert abs(sim.distance(target)) < 1e-10


def test_smm_distance_positive():
    target = cns_moments()
    sim = SimulatedMoments(
        values=target.values + 0.10,
        parameter_vector=np.array([0.5, 0.5]),
    )
    assert sim.distance(target) > 0


# ── LHS ───────────────────────────────────────────────────────────────────────

def test_lhs_shape_and_bounds():
    bounds = [(0.0, 1.0), (0.2, 0.8), (10.0, 20.0)]
    samples = latin_hypercube_sample(bounds, n_samples=50, seed=0)
    assert samples.shape == (50, 3)
    for j, (lo, hi) in enumerate(bounds):
        assert np.all(samples[:, j] >= lo)
        assert np.all(samples[:, j] <= hi)


def test_lhs_stratified():
    """Each dimension should have samples spread across all strata."""
    samples = latin_hypercube_sample([(0.0, 1.0)], n_samples=10, seed=0)
    # With 10 strata each of width 0.1, every stratum should be covered.
    bins = np.floor(samples[:, 0] * 10).astype(int)
    assert len(set(bins)) == 10, "LHS not stratified across all 10 strata"


# ── MLPSurrogate ──────────────────────────────────────────────────────────────

def test_mlp_surrogate_fit_predict():
    rng = np.random.default_rng(0)
    X = rng.uniform(0, 1, (60, 2))
    y = rng.uniform(0, 1, (60, 6))
    surrogate = MLPSurrogate()
    surrogate.fit(X, y)
    # predict() expects a single 1D parameter vector
    pred = surrogate.predict(X[0])
    assert pred.shape == (6,)


# ── Full pipeline smoke test ───────────────────────────────────────────────────

def test_run_smm_pipeline_smoke():
    """Smoke test: run SMM with minimal samples to verify the full pipeline."""
    from clinfish.core.engine import SimConfig, run_simulation

    target = cns_moments()
    bounds = [(0.2, 0.8), (0.2, 0.8)]

    def simulator(params):
        return run_simulation(SimConfig(
            therapeutic_area="cns",
            n_patients=100,
            n_sites=5,
            n_rounds=12,
            protocol_burden=params[0],
            protocol_visit_burden=params[1],
            seed=0,
        ))

    def moment_extractor(out):
        rounds = out.round_snapshots
        n = out.n_patients
        if not rounds:
            return [0.0] * 6
        r6  = next((r for r in rounds if r.time_months >= 6),  rounds[-1])
        r18 = next((r for r in rounds if r.time_months >= 12), rounds[-1])
        last = next((r for r in reversed(rounds) if r.n_enrolled > 0), rounds[-1])
        return [
            r6.n_dropout  / max(n, 1),
            r18.n_dropout / max(n, 1),
            last.mean_adherence,
            last.visit_compliance_rate,
            last.data_quality,
            last.ae_reporting_mean,
        ]

    result = run_smm(
        simulator=simulator,
        moment_extractor=moment_extractor,
        target=target,
        bounds=bounds,
        n_lhs=20,        # tiny grid for speed
        n_top_verify=2,
    )
    assert "best_params" in result
    assert "best_distance" in result
    assert "elapsed_seconds" in result
    assert len(result["best_params"]) == 2
    assert result["best_distance"] >= 0
    assert result["elapsed_seconds"] > 0
