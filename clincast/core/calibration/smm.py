"""Simulated Method of Moments calibration framework.

Follows Lamperti, Roventini & Sani (2018), Journal of Economic Dynamics
and Control 90:366-389. The key idea: running the full simulator at every
candidate parameter vector is too expensive for Nelder-Mead (~28,000 evals),
so we train a neural network surrogate on (θ, moments) pairs and optimize
on the surrogate.

The pipeline:
  1. Latin-hypercube sample the parameter space (200-500 draws).
  2. Run the fast vectorized simulator at each draw.
  3. Compute 6 simulated moments per run.
  4. Fit an MLP surrogate: θ → moments.
  5. Nelder-Mead on the SMM objective using the surrogate.
  6. Re-run the top-5 candidates on the real simulator to confirm.

The SMM objective is the weighted quadratic distance:

    J(θ) = (m_sim(θ) - m_target)' W (m_sim(θ) - m_target)

where W = diag(1/SE²). Moments with smaller standard errors carry more
weight because they were measured more precisely.

This is the same calibration architecture as SwarmCast v2, adapted
for clinical trial moments instead of GDPR/AI-Act moments.
"""

from __future__ import annotations

import dataclasses
import json
import math
from typing import Callable, Sequence

import numpy as np


# ─────────────────────────────────────────────────────────────────────────────
# MOMENT CONTAINER
# ─────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class TargetMoments:
    """Empirical targets the calibration minimizes distance from.

    Clinical moments are documented in clincast/core/calibration/moments.py
    with full citations. They are passed in here so the SMM framework itself
    stays domain-agnostic.

    se fields are standard errors estimated from cross-study variance in the
    underlying literature. They enter the weighting matrix as 1/SE², so a
    well-measured moment (small SE) pulls the optimizer harder than a noisy one.
    """

    values: np.ndarray   # shape (n_moments,)
    ses: np.ndarray      # shape (n_moments,) — standard errors
    names: list[str]     # human-readable label per moment, for reporting

    def __post_init__(self) -> None:
        if self.values.shape != self.ses.shape:
            raise ValueError("values and ses must have the same length")
        if len(self.names) != len(self.values):
            raise ValueError("names length must match values length")
        if np.any(self.ses <= 0):
            raise ValueError("all standard errors must be positive")

    @property
    def n(self) -> int:
        return len(self.values)

    def weighting_matrix(self) -> np.ndarray:
        """Diagonal weighting matrix W = diag(1/SE²)."""
        return np.diag(1.0 / (self.ses ** 2))


@dataclasses.dataclass
class SimulatedMoments:
    """Moments computed from one simulation run."""

    values: np.ndarray   # shape (n_moments,), same ordering as TargetMoments
    parameter_vector: np.ndarray

    def distance(self, target: TargetMoments) -> float:
        """Weighted quadratic SMM objective J(θ)."""
        d = self.values - target.values
        W = target.weighting_matrix()
        return float(d @ W @ d)

    def theil_u(self, target: TargetMoments) -> dict[str, float]:
        """Theil's inequality statistic for historical-fit assessment.

        Decomposes mean squared error into three components:
          UM (bias):      systematic mean error — should be near 0
          US (variance):  unequal variation — should be near 0
          UC (covariance): unsystematic error — should dominate

        Following Sterman (1984), Dynamica Vol. 10 (Winter), pp. 51–66.
        A well-validated model has UM + US ≈ 0 and UC ≈ 1.0.

        Returns dict with keys: U, UM, US, UC.
        """
        m_sim, m_obs = self.values, target.values
        mse = float(np.mean((m_sim - m_obs) ** 2))
        if mse < 1e-12:
            return {"U": 0.0, "UM": 0.0, "US": 0.0, "UC": 1.0}

        mean_sim, mean_obs = float(m_sim.mean()), float(m_obs.mean())
        std_sim,  std_obs  = float(m_sim.std()),  float(m_obs.std())
        rho = float(np.corrcoef(m_sim, m_obs)[0, 1]) if len(m_sim) > 1 else 1.0

        um = (mean_sim - mean_obs) ** 2 / mse
        us = (std_sim - std_obs) ** 2 / mse
        uc = 2.0 * (1.0 - rho) * std_sim * std_obs / mse

        # Normalize to sum to 1 (numerical precision)
        total = um + us + uc
        return {
            "U":  math.sqrt(mse) / (math.sqrt(float(np.mean(m_obs**2))) + 1e-12),
            "UM": um / total,
            "US": us / total,
            "UC": uc / total,
        }


# ─────────────────────────────────────────────────────────────────────────────
# MOMENT EXTRACTOR TYPE
# ─────────────────────────────────────────────────────────────────────────────

MomentExtractor = Callable[[dict], np.ndarray]
# A function that takes a simulation result dict and returns a moments array.
# Defined by the caller so the SMM framework stays domain-agnostic.


# ─────────────────────────────────────────────────────────────────────────────
# LATIN-HYPERCUBE SAMPLER
# ─────────────────────────────────────────────────────────────────────────────

def latin_hypercube_sample(
    bounds: list[tuple[float, float]],
    n_samples: int,
    seed: int = 0,
) -> np.ndarray:
    """Draw n_samples parameter vectors via Latin Hypercube Sampling.

    LHS ensures each parameter's range is divided into n_samples equal strata
    with exactly one sample per stratum. This gives much better coverage than
    uniform random sampling for the same budget.

    Returns array of shape (n_samples, n_params).
    """
    rng = np.random.default_rng(seed)
    n_params = len(bounds)
    result = np.zeros((n_samples, n_params))

    for j, (lo, hi) in enumerate(bounds):
        strata = rng.permutation(n_samples)
        u = (strata + rng.uniform(size=n_samples)) / n_samples
        result[:, j] = lo + u * (hi - lo)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# SURROGATE MODEL
# ─────────────────────────────────────────────────────────────────────────────

class MLPSurrogate:
    """Lightweight MLP trained on (θ, moments) pairs.

    Architecture: 64-64-32 hidden layers with ReLU, following SwarmCast v2.
    Uses scikit-learn MLPRegressor so there is no PyTorch/JAX dependency.

    The surrogate makes Nelder-Mead tractable: each surrogate eval takes
    microseconds vs. ~2s for the real simulator.
    """

    def __init__(self) -> None:
        self._model = None
        self._is_fitted = False

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """Train on parameter vectors X (n, p) and moment outputs y (n, m)."""
        from sklearn.neural_network import MLPRegressor
        from sklearn.preprocessing import StandardScaler

        self._x_scaler = StandardScaler()
        self._y_scaler = StandardScaler()
        X_s = self._x_scaler.fit_transform(X)
        y_s = self._y_scaler.fit_transform(y)

        self._model = MLPRegressor(
            hidden_layer_sizes=(64, 64, 32),
            activation="relu",
            max_iter=2000,
            random_state=0,
        )
        self._model.fit(X_s, y_s)
        self._is_fitted = True

    def predict(self, theta: np.ndarray) -> np.ndarray:
        """Predict moments for a single parameter vector."""
        if not self._is_fitted:
            raise RuntimeError("Surrogate not fitted — call fit() first")
        X_s = self._x_scaler.transform(theta.reshape(1, -1))
        y_s = self._model.predict(X_s)
        return self._y_scaler.inverse_transform(y_s)[0]


# ─────────────────────────────────────────────────────────────────────────────
# SMM OPTIMIZER
# ─────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class SMMResult:
    theta_star: np.ndarray
    objective_value: float
    surrogate_objective: float
    n_simulator_calls: int
    convergence_message: str
    top_candidates: list[tuple[np.ndarray, float]]  # (theta, J) sorted by J


def _newey_west_covariance(moments_matrix: np.ndarray, bandwidth: int | None = None) -> np.ndarray:
    """Newey-West HAC covariance estimator for the optimal SMM weighting matrix.

    Computes the long-run variance Ω̂ from simulated moment draws.
    Bandwidth b = floor{4 × (T/100)^(2/9)} follows Ruge-Murcia (CIREQ 2012).

    Used as the 2nd-step optimal weighting matrix W = Ω̂⁻¹, yielding the
    efficient GMM/MSM estimator. Reference: McFadden (1989), Econometrica.
    """
    T, k = moments_matrix.shape
    mean = moments_matrix.mean(axis=0)
    centered = moments_matrix - mean

    if bandwidth is None:
        bandwidth = max(1, int(4 * (T / 100) ** (2 / 9)))

    gamma_0 = (centered.T @ centered) / T
    omega = gamma_0.copy()
    for l in range(1, bandwidth + 1):
        bartlett = 1.0 - l / (bandwidth + 1.0)
        gamma_l = (centered[l:].T @ centered[:-l]) / T
        omega += bartlett * (gamma_l + gamma_l.T)

    return omega


def run_smm(
    simulator: Callable[[np.ndarray], dict],
    moment_extractor: MomentExtractor,
    target: TargetMoments,
    bounds: list[tuple[float, float]],
    n_lhs: int = 300,
    n_top_verify: int = 5,
    two_step: bool = False,
    seed: int = 0,
) -> dict:
    """Full SMM calibration pipeline.

    Args:
        simulator:         Callable θ → simulation result dict. Should be the
                           fast vectorized simulator, not the LLM swarm mode.
        moment_extractor:  Callable result_dict → np.ndarray of moments.
        target:            Empirical target moments with standard errors.
        bounds:            [(lo, hi)] for each parameter in θ.
        n_lhs:             Number of LHS draws for surrogate training.
        n_top_verify:      Top-N surrogate candidates to re-run on real sim.
        two_step:          If True, run a second-step optimization with
                           the Newey-West optimal weighting matrix Ω̂⁻¹,
                           yielding the efficient MSM estimator.
                           Requires n_lhs additional simulator calls.
                           Source: McFadden (1989) Econometrica 57(5):995.
        seed:              RNG seed for reproducibility.
    """
    import time as _time
    from scipy.optimize import minimize

    _t0 = _time.perf_counter()

    # Step 1 — LHS sample + simulate
    lhs_thetas = latin_hypercube_sample(bounds, n_lhs, seed=seed)
    lhs_moments = np.zeros((n_lhs, target.n))

    for i, theta in enumerate(lhs_thetas):
        result = simulator(theta)
        lhs_moments[i] = moment_extractor(result)

    # Step 2 — Fit surrogate
    surrogate = MLPSurrogate()
    surrogate.fit(lhs_thetas, lhs_moments)

    # Step 3 — Nelder-Mead on surrogate
    def surrogate_objective(theta: np.ndarray) -> float:
        theta = np.clip(theta, [b[0] for b in bounds], [b[1] for b in bounds])
        m_pred = surrogate.predict(theta)
        d = m_pred - target.values
        W = target.weighting_matrix()
        return float(d @ W @ d)

    # Start from best LHS draw
    lhs_objectives = np.array([
        SimulatedMoments(lhs_moments[i], lhs_thetas[i]).distance(target)
        for i in range(n_lhs)
    ])
    theta_init = lhs_thetas[np.argmin(lhs_objectives)]

    opt = minimize(surrogate_objective, theta_init, method="Nelder-Mead",
                   options={"maxiter": 50_000, "xatol": 1e-6, "fatol": 1e-8})

    # Step 3b — Two-step optimal weighting (optional)
    # Re-estimate W = Ω̂⁻¹ using simulated moment draws at the first-step θ̂,
    # then re-run Nelder-Mead with the efficient weighting matrix.
    # Source: McFadden (1989) Econometrica; Ruge-Murcia (CIREQ 2012).
    if two_step:
        # Simulate n_lhs draws at the first-step optimum to estimate Ω̂
        theta_1 = np.clip(opt.x, [b[0] for b in bounds], [b[1] for b in bounds])
        bootstrap_moments = np.zeros((n_lhs, target.n))
        for i in range(n_lhs):
            res_i = simulator(theta_1)
            bootstrap_moments[i] = moment_extractor(res_i)

        omega = _newey_west_covariance(bootstrap_moments)
        try:
            W2 = np.linalg.inv(omega + np.eye(target.n) * 1e-8)
        except np.linalg.LinAlgError:
            W2 = np.diag(1.0 / (target.ses ** 2))  # fallback to diagonal

        def surrogate_objective_2step(theta: np.ndarray) -> float:
            theta = np.clip(theta, [b[0] for b in bounds], [b[1] for b in bounds])
            m_pred = surrogate.predict(theta)
            d = m_pred - target.values
            return float(d @ W2 @ d)

        opt = minimize(surrogate_objective_2step, theta_1, method="Nelder-Mead",
                       options={"maxiter": 50_000, "xatol": 1e-6, "fatol": 1e-8})

    # Step 4 — Re-verify top candidates on real simulator
    # Sort LHS draws by surrogate objective and pick top candidates
    surrogate_objs = np.array([surrogate_objective(t) for t in lhs_thetas])
    top_idx = np.argsort(surrogate_objs)[:n_top_verify]
    candidates = []
    for idx in top_idx:
        result = simulator(lhs_thetas[idx])
        m = moment_extractor(result)
        j = SimulatedMoments(m, lhs_thetas[idx]).distance(target)
        candidates.append((lhs_thetas[idx].copy(), j))

    # Also verify the Nelder-Mead optimum
    theta_nm = np.clip(opt.x, [b[0] for b in bounds], [b[1] for b in bounds])
    result_nm = simulator(theta_nm)
    m_nm = moment_extractor(result_nm)
    j_nm = SimulatedMoments(m_nm, theta_nm).distance(target)
    candidates.append((theta_nm, j_nm))
    candidates.sort(key=lambda x: x[1])

    theta_star, j_star = candidates[0]

    return {
        "best_params":        theta_star,
        "best_distance":      j_star,
        "surrogate_objective": opt.fun,
        "n_simulator_calls":  n_lhs + n_top_verify + 1,
        "convergence_message": opt.message,
        "top_candidates":     candidates,
        "elapsed_seconds":    _time.perf_counter() - _t0,
    }
