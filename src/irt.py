"""2-parameter logistic (2PL) item response theory for eval items.

Why IRT belongs in an eval-science toolkit: raw accuracy stops discriminating
once models cluster near the top of a benchmark, but a latent-ability model keeps
resolving differences, and it tells you *which items* carry information. Assay uses
2PL to (1) estimate a per-item difficulty and discrimination, (2) place models on a
common ability scale with credible intervals, and (3) select Fisher-information
"fast subsets" that reproduce a full-benchmark ranking at a fraction of the items.

Model
-----
    P(correct | model m, item i) = sigmoid( a_i * (theta_m - b_i) )

with a_i > 0 (discrimination), b_i (difficulty), theta_m (ability). This module
fits by MAP / joint maximum likelihood with weak priors (N(0,1) on theta and on
log a, a wide N(0,5) on b) using scipy L-BFGS with analytic gradients. That keeps
the dependency footprint to numpy + scipy.

Honesty
-------
Joint ML is transparent and dependency-light but is the simple fitter, not the
production one: at very large scale the principled choice is marginal ML (EM) or a
variational fit. The priors anchor the otherwise-unidentified scale and location.
This is a *trained-model* component (gradient descent on thousands of parameters),
and it is validated here by parameter recovery on data simulated from known truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.optimize import minimize, minimize_scalar


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.tanh(0.5 * x))


@dataclass
class IRTFit:
    theta: np.ndarray      # (M,) model abilities
    a: np.ndarray          # (I,) item discriminations (>0)
    b: np.ndarray          # (I,) item difficulties
    n_models: int
    n_items: int
    loglik: float          # data log-likelihood at the fit (no prior term)
    converged: bool

    def prob(self) -> np.ndarray:
        """Full (M, I) matrix of predicted correctness probabilities."""
        return sigmoid(self.a[None, :] * (self.theta[:, None] - self.b[None, :]))


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-3, 1 - 1e-3)
    return np.log(p / (1 - p))


def fit_2pl(
    outcomes: np.ndarray,
    mask: Optional[np.ndarray] = None,
    prior_theta: float = 1.0,
    prior_b: float = 5.0,
    prior_loga: float = 1.0,
    maxiter: int = 500,
) -> IRTFit:
    """Fit a 2PL model to a (models x items) binary outcome matrix.

    ``mask`` marks observed entries (1) vs missing (0); missing entries do not
    contribute to the likelihood, so ragged leaderboards are fine.
    """
    Y = np.asarray(outcomes, dtype=float)
    if Y.ndim != 2:
        raise ValueError("outcomes must be a 2-D (models x items) matrix")
    M, I = Y.shape
    W = np.ones_like(Y) if mask is None else np.asarray(mask, dtype=float)

    # Sensible initial values from marginal means (respecting the mask).
    model_mean = (Y * W).sum(1) / np.clip(W.sum(1), 1, None)
    item_mean = (Y * W).sum(0) / np.clip(W.sum(0), 1, None)
    theta0 = _logit(model_mean)
    b0 = -_logit(item_mean)
    loga0 = np.zeros(I)
    x0 = np.concatenate([theta0, b0, loga0])

    def unpack(x):
        return x[:M], x[M:M + I], x[M + I:]

    def objective(x):
        theta, b, loga = unpack(x)
        a = np.exp(loga)
        z = a[None, :] * (theta[:, None] - b[None, :])
        p = np.clip(sigmoid(z), 1e-9, 1 - 1e-9)
        ll = W * (Y * np.log(p) + (1 - Y) * np.log(1 - p))
        nll = -ll.sum()
        pen = (0.5 * (theta ** 2).sum() / prior_theta ** 2
               + 0.5 * (b ** 2).sum() / prior_b ** 2
               + 0.5 * (loga ** 2).sum() / prior_loga ** 2)
        R = (p - Y) * W
        g_theta = (R * a[None, :]).sum(1) + theta / prior_theta ** 2
        g_b = -(a[None, :] * R).sum(0) + b / prior_b ** 2
        g_loga = a * (R * (theta[:, None] - b[None, :])).sum(0) + loga / prior_loga ** 2
        return nll + pen, np.concatenate([g_theta, g_b, g_loga])

    res = minimize(objective, x0, jac=True, method="L-BFGS-B",
                   options={"maxiter": maxiter, "ftol": 1e-10})
    theta, b, loga = unpack(res.x)
    a = np.exp(loga)

    # Fix the residual scale/sign gauge: center ability so the model is identified.
    theta = theta - theta.mean()
    p = np.clip(sigmoid(a[None, :] * (theta[:, None] - b[None, :])), 1e-9, 1 - 1e-9)
    loglik = float((W * (Y * np.log(p) + (1 - Y) * np.log(1 - p))).sum())
    return IRTFit(theta=theta, a=a, b=b, n_models=M, n_items=I,
                  loglik=loglik, converged=bool(res.success))


def item_information(theta: float | np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Fisher information each item contributes at ability ``theta``.

    I_i(theta) = a_i^2 * p_i * (1 - p_i). Peaks where the item difficulty matches
    the ability, and scales with discrimination squared.
    """
    theta = np.asarray(theta, dtype=float)
    p = sigmoid(a * (theta - b))
    return a ** 2 * p * (1 - p)


def select_fast_subset(
    a: np.ndarray,
    b: np.ndarray,
    k: int,
    theta_grid: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Indices of the ``k`` items carrying the most average Fisher information.

    Averaging over a grid of abilities selects items that are informative across
    the population of models, not just at a single point.
    """
    if theta_grid is None:
        theta_grid = np.linspace(-2.0, 2.0, 9)
    info = np.zeros(len(a))
    for t in theta_grid:
        info += item_information(t, a, b)
    info /= len(theta_grid)
    return np.argsort(info)[::-1][:k]


def estimate_ability(
    responses: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
    mask: Optional[np.ndarray] = None,
) -> tuple[float, float]:
    """MAP estimate of a model's ability from its responses on scored items.

    Returns (theta_hat, se). SE is 1/sqrt(total information + prior precision) at
    the estimate. Lets a brand-new model be placed on the scale from a subset.
    """
    r = np.asarray(responses, dtype=float)
    w = np.ones_like(r) if mask is None else np.asarray(mask, dtype=float)

    def nlp(theta):
        p = np.clip(sigmoid(a * (theta - b)), 1e-9, 1 - 1e-9)
        ll = (w * (r * np.log(p) + (1 - r) * np.log(1 - p))).sum()
        return -ll + 0.5 * theta ** 2  # N(0,1) prior

    res = minimize_scalar(nlp, bounds=(-6, 6), method="bounded")
    theta_hat = float(res.x)
    info = float((w * item_information(theta_hat, a, b)).sum()) + 1.0  # +1 for the prior
    return theta_hat, float(1.0 / np.sqrt(info))


def simulate_2pl(
    theta: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
    seed: int = 0,
    missing: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Draw a (models x items) outcome matrix from known 2PL parameters.

    Used to validate the fitter by parameter recovery (fit simulated data, check
    the recovered parameters correlate with truth) and to demo fast subsets.
    Returns (outcomes, mask). ``missing`` is the fraction of entries hidden.
    """
    rng = np.random.default_rng(seed)
    theta = np.asarray(theta, float); a = np.asarray(a, float); b = np.asarray(b, float)
    p = sigmoid(a[None, :] * (theta[:, None] - b[None, :]))
    Y = (rng.random(p.shape) < p).astype(float)
    if missing > 0:
        mask = (rng.random(p.shape) >= missing).astype(float)
    else:
        mask = np.ones_like(Y)
    return Y, mask
