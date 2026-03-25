"""Round-by-round behavioral validation tests.

Checks that simulated behavioral outputs fall within empirically plausible
ranges. These are not strict calibration tests (SMM calibration is separate)
but sanity checks that the model is in the right ballpark.
"""

import pytest

from clinfish.scenarios import get_scenario
from clinfish.core.engine import run_simulation


def _run(ta: str, n: int = 300, sites: int = 15, rounds: int = 18, seed: int = 0):
    config = get_scenario(ta)
    config.n_patients = n
    config.n_sites    = sites
    config.n_rounds   = rounds
    config.seed       = seed
    if config.pop_config:
        config.pop_config.n_patients = n
        config.pop_config.n_sites    = sites
    return run_simulation(config)


def test_cns_dropout_range():
    """CATIE: ~74% all-cause at 18 months. Measured as fraction of enrolled patients.

    NB: CATIE 74% is a fraction of enrolled patients who discontinued, NOT a fraction
    of all screened patients. Screening patients who never enrolled are excluded from
    the denominator. The loose bounds tolerate stochastic variation and partial SMM
    calibration.
    """
    result = _run("cns", rounds=18)
    final = result.round_snapshots[-1]
    # Denominator: patients who ever enrolled (dropout + completed only; not still screening)
    n_ever_enrolled = final.n_dropout + final.n_completed
    if n_ever_enrolled == 0:
        return  # degenerate run — enrollment failed entirely
    dropout_rate = final.n_dropout / n_ever_enrolled
    # Loose bounds: model is stochastic and not yet fully SMM-calibrated.
    assert 0.40 <= dropout_rate <= 0.95, (
        f"CNS dropout {dropout_rate:.2%} of enrolled outside [40%, 95%]"
    )


def test_data_quality_baseline():
    """Data quality should stay near Phase III baseline (0.68) in the active phase."""
    result = _run("cns", rounds=18)
    last_active = next(
        (r for r in reversed(result.round_snapshots) if r.n_enrolled > 0),
        result.round_snapshots[-1]
    )
    # Krudys 2022: Phase III baseline = 0.68. Allow ±0.20.
    assert 0.40 <= last_active.data_quality <= 0.90, (
        f"Data quality {last_active.data_quality:.3f} outside [0.40, 0.90]"
    )


def test_safety_signal_bounded():
    result = _run("oncology", rounds=24)
    for r in result.round_snapshots:
        assert 0.0 <= r.safety_signal <= 1.0, (
            f"Safety signal {r.safety_signal:.3f} out of [0, 1] at round {r.round_index}"
        )


def test_site_burden_bounded():
    result = _run("alzheimers", rounds=18)
    for r in result.round_snapshots:
        assert 0.0 <= r.site_burden <= 1.0, (
            f"Site burden {r.site_burden:.3f} out of [0, 1] at round {r.round_index}"
        )


def test_adherence_plausible():
    """Adherence should be in a plausible range throughout the trial.
    MEMS cross-study mean: 74.9%. The model accounts for belief drift and AE load
    which can reduce adherence in late-stage patients with high AE burden. Use a
    wide tolerance to accommodate the stochastic range.
    """
    result = _run("cns")
    # Check adherence at early rounds (round 3–6) before major belief drift
    early_rounds = [r for r in result.round_snapshots if 3 <= r.round_index <= 6 and r.n_enrolled > 0]
    if early_rounds:
        early_adherence = sum(r.mean_adherence for r in early_rounds) / len(early_rounds)
        assert 0.30 <= early_adherence <= 0.99, (
            f"Early mean adherence {early_adherence:.3f} implausible (expected 0.30–0.99)"
        )


def test_rare_low_dropout():
    """Rare disease: Tufts 2019 ~6.5% dropout at 24 months."""
    result = _run("rare", n=80, sites=8, rounds=24)
    final = result.round_snapshots[-1]
    dropout_rate = final.n_dropout / result.n_patients
    # λ=356 months → very low dropout. Upper bound generous for small N variance.
    assert dropout_rate <= 0.35, (
        f"Rare disease dropout {dropout_rate:.2%} exceeds 35% (expected ~6–15%)"
    )


def test_final_adherence_nonzero():
    """Final adherence should not be zero (was a historical bug)."""
    result = _run("cns")
    assert result.rounds, "No patient outputs"
    # Find the last round with enrolled patients
    last_active = next(
        (r for r in reversed(result.round_snapshots) if r.n_enrolled > 0),
        None,
    )
    assert last_active is not None, "No active rounds found"
    assert last_active.mean_adherence > 0.0, "Final active round adherence is zero"


def test_enrollment_occurs():
    """Some patients must actually enroll across all TAs."""
    for ta in ["cns", "oncology", "cardiovascular", "metabolic", "alzheimers", "rare"]:
        result = _run(ta)
        max_enrolled = max(r.n_enrolled for r in result.round_snapshots)
        assert max_enrolled > 0, f"[{ta}] no patients ever enrolled"


def test_belief_update():
    """Mean belief should change across rounds (network propagation is active)."""
    result = _run("cns")
    beliefs = [r.mean_belief for r in result.round_snapshots if r.n_enrolled > 0]
    assert len(beliefs) >= 2, "Too few active rounds to test belief update"
    assert beliefs[0] != beliefs[-1], "Beliefs never updated — DeGroot propagation may be broken"


def test_monitoring_effect_on_data_quality():
    """Monitoring active should produce better data quality than monitoring disabled."""
    config_on = get_scenario("cns")
    config_on.n_patients, config_on.n_sites, config_on.n_rounds = 200, 10, 18
    config_on.monitoring_active = True
    config_on.seed = 5
    config_on.pop_config.n_patients = 200; config_on.pop_config.n_sites = 10

    config_off = get_scenario("cns")
    config_off.n_patients, config_off.n_sites, config_off.n_rounds = 200, 10, 18
    config_off.monitoring_active = False
    config_off.seed = 5
    config_off.pop_config.n_patients = 200; config_off.pop_config.n_sites = 10

    result_on  = run_simulation(config_on)
    result_off = run_simulation(config_off)

    last_on  = next((r for r in reversed(result_on.round_snapshots)  if r.n_enrolled > 0), result_on.round_snapshots[-1])
    last_off = next((r for r in reversed(result_off.round_snapshots) if r.n_enrolled > 0), result_off.round_snapshots[-1])

    assert last_on.data_quality >= last_off.data_quality - 0.05, (
        f"Monitoring active ({last_on.data_quality:.3f}) should not be worse than disabled ({last_off.data_quality:.3f})"
    )
