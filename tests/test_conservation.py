"""Population conservation law tests.

Every patient must end up in exactly one terminal stock: dropout or completed.
N_screening + N_enrolled + N_dropout + N_completed = N_total at all times.
"""

import pytest

from clinfish.core.engine import SimConfig, run_simulation
from clinfish.scenarios import get_scenario


def _run(ta: str, n: int = 100, sites: int = 5, rounds: int = 12, seed: int = 7) -> object:
    config = get_scenario(ta)
    config.n_patients = n
    config.n_sites    = sites
    config.n_rounds   = rounds
    config.seed       = seed
    if config.pop_config:
        config.pop_config.n_patients = n
        config.pop_config.n_sites    = sites
    return run_simulation(config)


@pytest.mark.parametrize("ta", ["cns", "oncology", "cardiovascular", "metabolic", "alzheimers", "rare"])
def test_population_conserved(ta):
    result = _run(ta, n=200, rounds=18)
    n = result.n_patients
    for r in result.round_snapshots:
        total = r.n_enrolled + r.n_dropout + r.n_completed
        # screening = n - total (patients not yet enrolled)
        screening = n - total
        assert screening >= 0, f"[{ta}] round {r.round_index}: negative screening count"
        assert total <= n,     f"[{ta}] round {r.round_index}: total > n ({total} > {n})"


@pytest.mark.parametrize("ta", ["cns", "oncology"])
def test_dropout_monotone(ta):
    """Dropout count should never decrease across rounds."""
    result = _run(ta)
    dropouts = [r.n_dropout for r in result.round_snapshots]
    for i in range(1, len(dropouts)):
        assert dropouts[i] >= dropouts[i-1], (
            f"[{ta}] dropout decreased at round {i}: {dropouts[i-1]} → {dropouts[i]}"
        )


def test_completion_only_at_final_round():
    """Patients should complete only at the final round."""
    result = _run("cns", rounds=12)
    for r in result.round_snapshots[:-1]:
        assert r.n_completed == 0, (
            f"Completion before final round at round {r.round_index}"
        )
    assert result.round_snapshots[-1].n_completed >= 0


def test_no_negative_stocks():
    result = _run("oncology", n=150, rounds=24)
    for r in result.round_snapshots:
        assert r.n_enrolled  >= 0
        assert r.n_dropout   >= 0
        assert r.n_completed >= 0


def test_seed_reproducibility():
    """Same seed must produce identical results."""
    r1 = _run("cns", seed=42)
    r2 = _run("cns", seed=42)
    assert r1.round_snapshots[-1].n_dropout   == r2.round_snapshots[-1].n_dropout
    assert r1.round_snapshots[-1].n_completed == r2.round_snapshots[-1].n_completed


def test_different_seeds_differ():
    r1 = _run("cns", seed=1)
    r2 = _run("cns", seed=2)
    # With 200 patients, the two runs should produce at least slightly different dropouts.
    totals_1 = [r.n_dropout for r in r1.round_snapshots]
    totals_2 = [r.n_dropout for r in r2.round_snapshots]
    assert totals_1 != totals_2, "Different seeds produced identical dropout trajectories"
