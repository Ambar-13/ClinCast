"""Structural sensitivity analysis — verifies qualitative behavior modes are preserved
under parameter variation.

Forrester & Senge (1980) requirement: a model should respond to parameter changes in
the expected qualitative direction. These tests do not check precise numerical values;
they verify that the causal structure of the model is correct.

References:
  - Forrester JW & Senge PM (1980). Tests for Building Confidence in SD Models.
    TIMS Studies in Management Sciences, Vol. 14, pp. 209–228.
  - Barlas Y (1996). Formal Aspects of Model Validity. System Dynamics Review 12(3).
"""

import numpy as np
import pytest

from clinfish.core.engine import SimConfig, run_simulation
from clinfish.domain.response import adherence_probability
from clinfish.domain.agents import ArchetypeID


# ── Helper ────────────────────────────────────────────────────────────────────

def _run(ta: str = "cns", n: int = 300, sites: int = 15, rounds: int = 24,
         seed: int = 42, **kwargs):
    config = SimConfig(
        therapeutic_area=ta,
        n_patients=n,
        n_sites=sites,
        n_rounds=rounds,
        seed=seed,
        **kwargs,
    )
    return run_simulation(config)


# ── Test 1: Weibull shape κ < 1 vs κ > 1 — dropout timing direction ──────────

def test_weibull_shape_dropout_direction():
    """κ < 1 should produce relatively more early dropout; κ > 1 more late dropout.

    Weibull hazard h(t) ∝ κ * t^(κ-1): decreasing for κ<1, increasing for κ>1.
    FIX M15 (M4): Structural sensitivity test — Forrester & Senge (1980).
    """
    res_low  = _run(shape_k=0.5, n=400, rounds=24, seed=7)
    res_high = _run(shape_k=1.6, n=400, rounds=24, seed=7)

    snaps_low  = res_low.round_snapshots
    snaps_high = res_high.round_snapshots

    total_dropout_low  = snaps_low[-1].n_dropout
    total_dropout_high = snaps_high[-1].n_dropout

    if total_dropout_low == 0 or total_dropout_high == 0:
        pytest.skip("Insufficient dropout to test shape direction (degenerate run)")

    # κ < 1: more dropout in first 6 rounds relative to total
    n_early_rounds = min(6, len(snaps_low))
    early_dropout_low  = snaps_low[n_early_rounds - 1].n_dropout
    early_dropout_high = snaps_high[n_early_rounds - 1].n_dropout

    frac_early_low  = early_dropout_low  / total_dropout_low
    frac_early_high = early_dropout_high / total_dropout_high

    assert frac_early_low > frac_early_high - 0.05, (
        f"κ=0.5 should produce relatively more early dropout than κ=1.6. "
        f"Got frac_early: κ<1={frac_early_low:.3f}, κ>1={frac_early_high:.3f}"
    )


# ── Test 2: enrollment_rate_modifier monotonic ───────────────────────────────

def test_enrollment_rate_modifier_monotonic():
    """Higher enrollment_rate_modifier should produce more enrolled patients.

    Structural sensitivity: enrollment flow should respond monotonically to
    the rate modifier. FIX M15 (M4): Forrester & Senge (1980).
    """
    modifiers = [0.3, 0.7, 1.0, 1.5]
    totals_processed = []
    for modifier in modifiers:
        res = _run(enrollment_rate_modifier=modifier, n=500, rounds=18, seed=99)
        final = res.round_snapshots[-1]
        # Count all patients who ever moved out of screening
        totals_processed.append(final.n_dropout + final.n_completed + final.n_enrolled)

    # Monotonically non-decreasing (allow small slack of 20 for stochasticity)
    for i in range(len(totals_processed) - 1):
        assert totals_processed[i] <= totals_processed[i + 1] + 20, (
            f"Enrollment should increase with rate modifier: "
            f"modifiers={modifiers}, totals={totals_processed}"
        )


# ── Test 3: Protocol burden → adherence direction ────────────────────────────

def test_protocol_burden_reduces_adherence():
    """Higher site burden should produce lower or equal mean adherence.

    FIX M15 (M4): Structural sensitivity — protocol burden is an input to
    adherence_probability; direction should be negative.
    """
    res_low  = _run(protocol_burden=0.1, n=200, rounds=12, seed=3)
    res_high = _run(protocol_burden=0.9, n=200, rounds=12, seed=3)

    # Compare mean adherence across all active rounds
    def mean_active_adherence(result):
        active = [r.mean_adherence for r in result.round_snapshots if r.n_enrolled > 0]
        return float(np.mean(active)) if active else 0.0

    adh_low  = mean_active_adherence(res_low)
    adh_high = mean_active_adherence(res_high)

    assert adh_low >= adh_high - 0.05, (
        f"Lower protocol burden should produce higher or equal adherence. "
        f"Got adh_low={adh_low:.3f}, adh_high={adh_high:.3f}"
    )


# ── Test 4: Neuroticism reduces adherence (unit-level) ───────────────────────

def test_neuroticism_reduces_adherence():
    """Higher Neuroticism population should have lower adherence probability.

    Tests the adherence_probability function directly at the unit level.
    FIX M15 (M4): Structural sensitivity on domain function.
    """
    n_patients = 200
    archetype_ids = np.zeros(n_patients, dtype=np.int32)  # all archetype 0
    belief = np.full(n_patients, 0.6, dtype=np.float32)
    ae = np.zeros(n_patients, dtype=np.float32)
    low_n  = np.full(n_patients, 0.2, dtype=np.float32)
    high_n = np.full(n_patients, 0.8, dtype=np.float32)

    adh_low  = adherence_probability(
        archetype_ids, belief, ae, 0.3, 6.0, neuroticism=low_n
    ).mean()
    adh_high = adherence_probability(
        archetype_ids, belief, ae, 0.3, 6.0, neuroticism=high_n
    ).mean()

    assert adh_low > adh_high, (
        f"Lower neuroticism should produce higher adherence. "
        f"Got adh(N=0.2)={adh_low:.4f}, adh(N=0.8)={adh_high:.4f}"
    )


# ── Test 5: Higher protocol burden increases site burden stock ────────────────

def test_protocol_burden_increases_site_burden():
    """Protocol burden should drive up the site burden stock over time.

    FIX M15 (M4): Structural sensitivity — site_burden is a stock driven
    by protocol_burden inflow; higher input should produce higher stock.
    """
    res_low  = _run(protocol_burden=0.05, n=200, rounds=18, seed=0)
    res_high = _run(protocol_burden=0.95, n=200, rounds=18, seed=0)

    final_burden_low  = res_low.round_snapshots[-1].site_burden
    final_burden_high = res_high.round_snapshots[-1].site_burden

    assert final_burden_high >= final_burden_low, (
        f"High burden ({final_burden_high:.3f}) should not be lower than "
        f"low burden ({final_burden_low:.3f})"
    )


# ── Test 6: Dropout modifier direction ───────────────────────────────────────

def test_dropout_rate_modifier_direction():
    """Lower dropout_rate_modifier should produce lower cumulative dropout.

    FIX M15 (M4): Structural sensitivity — dropout_rate_modifier scales
    the per-patient hazard; direction must be monotone.
    """
    res_low  = _run(dropout_rate_modifier=0.1, n=300, rounds=18, seed=5)
    res_high = _run(dropout_rate_modifier=2.0, n=300, rounds=18, seed=5)

    dropout_low  = res_low.round_snapshots[-1].n_dropout
    dropout_high = res_high.round_snapshots[-1].n_dropout

    assert dropout_low <= dropout_high + 5, (
        f"Lower dropout modifier should produce less dropout. "
        f"Got dropout(0.1)={dropout_low}, dropout(2.0)={dropout_high}"
    )
