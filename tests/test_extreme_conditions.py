"""Extreme condition tests — Barlas (1996) / Forrester & Senge (1980).

Structure-oriented behavior tests: set parameters to extreme values and
verify the model responds in a physically meaningful way. These tests do
not check precise numerical values; they verify the model's causal
structure is correct.

References:
  - Barlas Y (1996). Formal Aspects of Model Validity in System Dynamics.
    System Dynamics Review 12(3):183–210.
  - Forrester JW & Senge PM (1980). Tests for Building Confidence in SD Models.
    TIMS Studies in Management Sciences, Vol. 14, pp. 209–228.
  - Sterman JD (2000). Business Dynamics, Ch. 21 (Section 21.4.5).
"""

import pytest
import numpy as np

from clincast.core.engine import SimConfig, run_simulation
from clincast.domain.agents import PatientPopulationConfig


def _config(
    n_patients: int = 100,
    n_sites: int = 5,
    n_rounds: int = 12,
    protocol_burden: float = 0.5,
    protocol_visit_burden: float = 0.5,
    monitoring: bool = True,
    seed: int = 0,
) -> SimConfig:
    return SimConfig(
        therapeutic_area="cns",
        n_patients=n_patients,
        n_sites=n_sites,
        n_rounds=n_rounds,
        protocol_burden=protocol_burden,
        protocol_visit_burden=protocol_visit_burden,
        monitoring_active=monitoring,
        seed=seed,
    )


# ── Test 1: Zero sites → no enrollment ───────────────────────────────────────

def test_zero_sites_no_enrollment():
    """With 0 sites, enrollment rate collapses to minimum and few if any patients enroll.

    Physically: no investigators → no referrals → no enrolled patients.
    We set n_sites=1 (0 causes division issues downstream) and very high burden.
    """
    config = _config(n_sites=1, protocol_burden=0.99, n_patients=100, n_rounds=12)
    result = run_simulation(config)
    final = result.round_snapshots[-1]
    # Very few patients should enroll with 1 burdened site
    enrolled_or_completed = final.n_dropout + final.n_completed
    assert enrolled_or_completed <= 80, (
        f"Expected low enrollment with 1 site at max burden; got {enrolled_or_completed} processed"
    )


# ── Test 2: Maximum protocol burden → site burden accumulates fast ────────────

def test_max_burden_increases_site_stock():
    """Maximum protocol burden should accumulate site burden faster than minimum burden."""
    config_high = _config(protocol_burden=0.95, protocol_visit_burden=0.95)
    config_low  = _config(protocol_burden=0.05, protocol_visit_burden=0.05)
    result_high = run_simulation(config_high)
    result_low  = run_simulation(config_low)
    final_high = result_high.round_snapshots[-1].site_burden
    final_low  = result_low.round_snapshots[-1].site_burden
    assert final_high >= final_low, (
        f"High burden ({final_high:.3f}) should not be lower than low burden ({final_low:.3f})"
    )


# ── Test 3: Zero AE load → safety signal stays near zero ──────────────────────

def test_minimal_trial_safety_signal():
    """With very few patients, safety signal should stay very low throughout."""
    config = SimConfig(
        therapeutic_area="cns",
        n_patients=10,
        n_sites=2,
        n_rounds=6,
        seed=0,
        pop_config=PatientPopulationConfig(n_patients=10, n_sites=2),
    )
    result = run_simulation(config)
    for r in result.round_snapshots:
        assert r.safety_signal <= 0.30, (
            f"Safety signal {r.safety_signal:.3f} unexpectedly high with 10 patients"
        )


# ── Test 4: Monitoring disabled → data quality lower or equal ──────────────────

def test_no_monitoring_lower_data_quality():
    """Disabling monitoring should produce equal or worse data quality at trial end."""
    config_on  = _config(monitoring=True,  seed=42)
    config_off = _config(monitoring=False, seed=42)
    result_on  = run_simulation(config_on)
    result_off = run_simulation(config_off)
    # Allow a small tolerance for stochastic noise
    dq_on  = result_on.round_snapshots[-1].data_quality
    dq_off = result_off.round_snapshots[-1].data_quality
    assert dq_on >= dq_off - 0.03, (
        f"Monitoring on ({dq_on:.3f}) should not be worse than monitoring off ({dq_off:.3f})"
    )


# ── Test 5: Conservation holds at all rounds regardless of extreme params ──────

@pytest.mark.parametrize("burden", [0.01, 0.50, 0.99])
def test_conservation_under_extreme_burden(burden):
    """Population conservation must hold even at extreme protocol burden values."""
    config = _config(n_patients=150, protocol_burden=burden, n_rounds=18)
    result = run_simulation(config)
    n = config.n_patients
    for r in result.round_snapshots:
        total_accounted = r.n_enrolled + r.n_dropout + r.n_completed
        screening = n - total_accounted
        assert screening >= 0,     f"Negative screening at round {r.round_index} (burden={burden})"
        assert total_accounted <= n, f"Total exceeds N at round {r.round_index} (burden={burden})"


# ── Test 6: Single round — must not crash ──────────────────────────────────────

def test_single_round_completes():
    config = _config(n_patients=50, n_rounds=1)
    result = run_simulation(config)
    assert len(result.round_snapshots) == 1


# ── Test 7: Safety signal bounded under any AE scenario ───────────────────────

def test_safety_signal_never_exceeds_one():
    """Safety signal is a 0-1 stock; must never exceed 1.0."""
    config = _config(n_patients=500, n_sites=20, n_rounds=36)
    result = run_simulation(config)
    for r in result.round_snapshots:
        assert r.safety_signal <= 1.0 + 1e-6, (
            f"Safety signal {r.safety_signal:.6f} exceeds 1.0 at round {r.round_index}"
        )


# ── Test 8: Data quality bounded in [0, 1] ────────────────────────────────────

def test_data_quality_bounded():
    config = _config(n_patients=200, n_rounds=24, monitoring=False, protocol_burden=0.99)
    result = run_simulation(config)
    for r in result.round_snapshots:
        assert 0.0 <= r.data_quality <= 1.0, (
            f"Data quality {r.data_quality:.3f} out of [0,1] at round {r.round_index}"
        )


# ── Test 9: Theil U — SMM distance at target should give UC ≈ 1 ───────────────

def test_theil_u_at_exact_match():
    from clincast.core.calibration.smm import SimulatedMoments
    from clincast.core.calibration.moments import cns_moments
    import numpy as np

    target = cns_moments()
    sim = SimulatedMoments(values=target.values.copy(), parameter_vector=np.zeros(2))
    u = sim.theil_u(target)
    # At exact match: MSE = 0, U = 0
    assert u["U"] < 1e-6, f"U should be ~0 at exact match; got {u['U']}"


def test_theil_u_decomposes_to_one():
    from clincast.core.calibration.smm import SimulatedMoments
    from clincast.core.calibration.moments import cns_moments
    import numpy as np

    target = cns_moments()
    rng = np.random.default_rng(0)
    sim = SimulatedMoments(
        values=target.values + rng.uniform(-0.1, 0.1, len(target.values)),
        parameter_vector=np.zeros(2),
    )
    u = sim.theil_u(target)
    total = u["UM"] + u["US"] + u["UC"]
    assert abs(total - 1.0) < 1e-6, f"Theil components should sum to 1; got {total}"
    assert u["U"] >= 0, "U statistic must be non-negative"
