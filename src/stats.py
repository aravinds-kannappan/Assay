"""Core statistics for eval measurement.

Every function is deterministic given its inputs and reports a *statistically
estimated* quantity. Nothing here calls a model or an LLM judge.

The design choices that matter:

* Cluster-robust SEs default to CR2 (Bell-McCaffrey bias reduction), which for
  the sample mean has the closed form  SE = sqrt( sum_g R_g^2 / (1 - n_g/n) ) / n
  where R_g is the sum of residuals in cluster g. CR0 understates uncertainty
  when a few clusters dominate, which is exactly the SWE-bench (~12 repos) and
  MMLU (57 subjects) regime. A pairs-cluster bootstrap is provided as a
  cross-check and is the honest fallback when the cluster count is small.

* The paired comparison is the load-bearing test. Exact McNemar is used when
  there is no cluster structure; a cluster-aware paired z-test (clustered SE on
  per-item score differences) is used when a cluster key is present.

* MDE / required-n follow Miller (arXiv:2411.00640, Eq 9): the (z_{1-a/2}+z_{1-b})^2
  factor is 7.849 at alpha=0.05, power=0.80.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
from scipy import stats as sps


# ---- helpers --------------------------------------------------------------

def _as_array(x: Sequence[float]) -> np.ndarray:
    a = np.asarray(list(x), dtype=float)
    if a.ndim != 1:
        raise ValueError("expected a 1-D sequence of per-item scores")
    if a.size == 0:
        raise ValueError("empty score vector")
    return a


def z_factor(alpha: float = 0.05, power: float = 0.8) -> float:
    """(z_{1-alpha/2} + z_{power}); equals 2.8016 at alpha=0.05, power=0.8."""
    return float(sps.norm.ppf(1 - alpha / 2) + sps.norm.ppf(power))


# ---- point estimate and i.i.d. SE ----------------------------------------

def mean_and_naive_se(scores: Sequence[float]) -> tuple[float, float]:
    """Mean and CLT standard error s/sqrt(n) (sample std, ddof=1)."""
    a = _as_array(scores)
    n = a.size
    mean = float(a.mean())
    if n == 1:
        return mean, float("nan")
    se = math.sqrt(float(a.var(ddof=1)) / n)
    return mean, se


# ---- cluster-robust SE ----------------------------------------------------

@dataclass
class ClusteredSE:
    mean: float
    naive_se: float
    cluster_se: float
    method: str
    n_items: int
    n_clusters: int
    inflation: float          # cluster_se / naive_se, the headline ratio
    small_cluster_warning: bool

    def ci(self, alpha: float = 0.05) -> tuple[float, float]:
        z = sps.norm.ppf(1 - alpha / 2)
        return self.mean - z * self.cluster_se, self.mean + z * self.cluster_se


def _cluster_sums(a: np.ndarray, clusters: Sequence) -> tuple[np.ndarray, np.ndarray]:
    """Return residual sums R_g and sizes n_g per cluster (residual = x - mean)."""
    resid = a - a.mean()
    groups: dict = {}
    for r, c in zip(resid, clusters):
        groups.setdefault(c, [0.0, 0])
        groups[c][0] += r
        groups[c][1] += 1
    R = np.array([v[0] for v in groups.values()], dtype=float)
    sizes = np.array([v[1] for v in groups.values()], dtype=float)
    return R, sizes


def cluster_robust_se(
    scores: Sequence[float],
    clusters: Sequence,
    method: str = "CR2",
    min_clusters: int = 30,
) -> ClusteredSE:
    """Cluster-robust SE of the mean.

    method: "CR0" | "CR1" | "CR2" (default). CR2 applies the Bell-McCaffrey
    leverage correction, which for the intercept-only mean inflates each
    cluster's residual sum by (1 - n_g/n)^{-1/2}.
    """
    a = _as_array(scores)
    clusters = list(clusters)
    if len(clusters) != a.size:
        raise ValueError("scores and clusters must have the same length")
    if any(c is None for c in clusters):
        raise ValueError("cluster key is None for at least one item; drop or impute first")

    n = a.size
    R, sizes = _cluster_sums(a, clusters)
    G = R.size

    if method.upper() == "CR0":
        var = float(np.sum(R ** 2)) / n ** 2
    elif method.upper() == "CR1":
        var = (G / (G - 1)) * float(np.sum(R ** 2)) / n ** 2 if G > 1 else float("nan")
    elif method.upper() == "CR2":
        adj = R ** 2 / (1.0 - sizes / n)
        var = float(np.sum(adj)) / n ** 2
    else:
        raise ValueError(f"unknown method {method!r}; use CR0, CR1, or CR2")

    cluster_se = math.sqrt(var) if var == var and var >= 0 else float("nan")
    _, naive_se = mean_and_naive_se(a)
    inflation = cluster_se / naive_se if naive_se and naive_se > 0 else float("nan")
    return ClusteredSE(
        mean=float(a.mean()),
        naive_se=naive_se,
        cluster_se=cluster_se,
        method=method.upper(),
        n_items=n,
        n_clusters=G,
        inflation=inflation,
        small_cluster_warning=G < min_clusters,
    )


def cluster_bootstrap_se(
    scores: Sequence[float],
    clusters: Sequence,
    n_boot: int = 2000,
    seed: int = 0,
) -> float:
    """Pairs-cluster bootstrap SE of the mean (resample whole clusters).

    Provided as a cross-check on CR2 and as the honest fallback when the number
    of clusters is small. Deterministic given ``seed``.
    """
    a = _as_array(scores)
    clusters = list(clusters)
    by_cluster: dict = {}
    for val, c in zip(a, clusters):
        by_cluster.setdefault(c, []).append(val)
    keys = list(by_cluster.keys())
    arrs = [np.asarray(by_cluster[k], dtype=float) for k in keys]
    G = len(keys)
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        pick = rng.integers(0, G, size=G)
        chosen = np.concatenate([arrs[i] for i in pick])
        means[b] = chosen.mean()
    return float(means.std(ddof=1))


# ---- paired comparison ----------------------------------------------------

@dataclass
class PairedResult:
    b_only: int          # a correct, b wrong
    c_only: int          # a wrong, b correct
    n_discordant: int
    delta: float         # mean(b) - mean(a)
    statistic: float
    p_value: float
    test: str            # "exact-mcnemar" | "clustered-paired-z"


def paired_mcnemar(a_correct: Sequence[float], b_correct: Sequence[float]) -> PairedResult:
    """Exact (binomial) McNemar test for two systems on the same items.

    Use when items are independent. If items share a source (a cluster key
    exists), use :func:`paired_clustered` instead.
    """
    a = _as_array(a_correct) > 0.5
    b = _as_array(b_correct) > 0.5
    if a.size != b.size:
        raise ValueError("paired inputs must have equal length")
    b_only = int(np.sum(a & ~b))
    c_only = int(np.sum(~a & b))
    n_disc = b_only + c_only
    delta = float(b.mean() - a.mean())
    if n_disc == 0:
        return PairedResult(b_only, c_only, 0, delta, 0.0, 1.0, "exact-mcnemar")
    p = float(sps.binomtest(min(b_only, c_only), n_disc, 0.5, alternative="two-sided").pvalue)
    stat = (abs(b_only - c_only) - 1) ** 2 / n_disc  # continuity-corrected chi-square, reported
    return PairedResult(b_only, c_only, n_disc, delta, stat, p, "exact-mcnemar")


def paired_clustered(
    a_correct: Sequence[float],
    b_correct: Sequence[float],
    clusters: Sequence,
    method: str = "CR2",
) -> PairedResult:
    """Cluster-aware paired test: clustered SE on per-item score differences.

    d_i = b_i - a_i; z = mean(d) / clustered_SE(d). This is the canonical gate
    test whenever items share a source, because independent-pairs McNemar on
    clustered items understates uncertainty.
    """
    a = _as_array(a_correct)
    b = _as_array(b_correct)
    if not (a.size == b.size == len(list(clusters))):
        raise ValueError("inputs and clusters must have equal length")
    d = b - a
    cse = cluster_robust_se(d, clusters, method=method)
    delta = float(d.mean())
    z = delta / cse.cluster_se if cse.cluster_se and cse.cluster_se > 0 else 0.0
    p = float(2 * sps.norm.sf(abs(z)))
    ab = _as_array(a_correct) > 0.5
    bb = _as_array(b_correct) > 0.5
    return PairedResult(
        b_only=int(np.sum(ab & ~bb)),
        c_only=int(np.sum(~ab & bb)),
        n_discordant=int(np.sum(ab ^ bb)),
        delta=delta,
        statistic=float(z),
        p_value=p,
        test="clustered-paired-z",
    )


# ---- power / minimum detectable effect ------------------------------------

def mde_absolute(n: int, p: float, alpha: float = 0.05, power: float = 0.8) -> float:
    """Smallest absolute accuracy gap an unpaired n-item eval can resolve.

    Uses per-item Bernoulli SD sqrt(p(1-p)); worst case p=0.5.
    """
    sigma = math.sqrt(max(p * (1 - p), 1e-12))
    return z_factor(alpha, power) * sigma / math.sqrt(n)


def mde_paired(n: int, sigma_diff: float, alpha: float = 0.05, power: float = 0.8) -> float:
    """Smallest paired accuracy gap resolvable given the SD of per-item diffs."""
    return z_factor(alpha, power) * sigma_diff / math.sqrt(n)


def required_n(effect: float, sigma: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Items needed to detect ``effect`` at the given sigma, alpha, power (Miller Eq 9)."""
    if effect <= 0:
        raise ValueError("effect must be positive")
    return int(math.ceil((z_factor(alpha, power) ** 2) * sigma ** 2 / effect ** 2))


# ---- multiple comparisons -------------------------------------------------

def holm(p_values: Sequence[float], alpha: float = 0.05) -> list[bool]:
    """Holm step-down: return a reject/accept mask controlling FWER at alpha."""
    p = list(p_values)
    m = len(p)
    order = sorted(range(m), key=lambda i: p[i])
    reject = [False] * m
    for rank, i in enumerate(order):
        thresh = alpha / (m - rank)
        if p[i] <= thresh:
            reject[i] = True
        else:
            break
    return reject


# ---- agreement (for judge validation) -------------------------------------

def agreement_rate(a: Sequence, b: Sequence) -> float:
    """Raw fraction of items where two raters agree. Deterministic."""
    a = list(a); b = list(b)
    if len(a) != len(b) or not a:
        raise ValueError("raters must be non-empty and equal length")
    return sum(1 for x, y in zip(a, b) if x == y) / len(a)


def cohens_kappa(a: Sequence, b: Sequence) -> float:
    """Cohen's kappa: agreement corrected for the agreement expected by chance.

    Raw agreement is inflated when one label dominates (an LLM judge that always
    says "A" agrees with a 50/50 human set half the time by luck); kappa removes
    that. Returns 0.0 in the degenerate case where chance agreement is 1.
    """
    a = list(a); b = list(b)
    if len(a) != len(b) or not a:
        raise ValueError("raters must be non-empty and equal length")
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    labels = set(a) | set(b)
    pe = sum((a.count(k) / n) * (b.count(k) / n) for k in labels)
    if 1 - pe <= 1e-12:
        return 0.0
    return (po - pe) / (1 - pe)


def kappa_bootstrap_ci(
    a: Sequence,
    b: Sequence,
    clusters: Optional[Sequence] = None,
    n_boot: int = 4000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float, float]:
    """Percentile bootstrap CI (and SE) for Cohen's kappa.

    If ``clusters`` is given, resamples whole clusters (cluster-aware), because
    items that share a source are not independent. Returns (lo, hi, se).
    """
    a = list(a); b = list(b)
    rng = np.random.default_rng(seed)
    n = len(a)
    if clusters is None:
        idx_pool = [[i] for i in range(n)]
    else:
        groups: dict = {}
        for i, c in enumerate(clusters):
            groups.setdefault(c, []).append(i)
        idx_pool = list(groups.values())
    G = len(idx_pool)
    ks = np.empty(n_boot)
    for it in range(n_boot):
        pick = rng.integers(0, G, size=G)
        idx = [i for g in pick for i in idx_pool[g]]
        ks[it] = cohens_kappa([a[i] for i in idx], [b[i] for i in idx])
    lo = float(np.quantile(ks, alpha / 2))
    hi = float(np.quantile(ks, 1 - alpha / 2))
    return lo, hi, float(ks.std(ddof=1))


def spearman(x: Sequence[float], y: Sequence[float]) -> tuple[float, float]:
    """Spearman rank correlation and its p-value (wraps scipy). Returns (rho, p)."""
    if len(list(x)) != len(list(y)):
        raise ValueError("x and y must have equal length")
    res = sps.spearmanr(list(x), list(y))
    return float(res.statistic), float(res.pvalue)


def pearson(x: Sequence[float], y: Sequence[float]) -> tuple[float, float]:
    """Pearson correlation and its p-value (wraps scipy). Returns (r, p)."""
    if len(list(x)) != len(list(y)):
        raise ValueError("x and y must have equal length")
    res = sps.pearsonr(list(x), list(y))
    return float(res.statistic), float(res.pvalue)


# ---- distributional shift (judge scores vs human scores) ------------------

def ks_test(a: Sequence[float], b: Sequence[float]) -> tuple[float, float]:
    """Two-sample Kolmogorov-Smirnov test. Returns (statistic, p_value).

    Asks whether two samples (e.g. a judge's 1-5 scores and the human scores on
    the same items) are drawn from the same distribution. A small p rejects "same".
    """
    res = sps.ks_2samp(list(a), list(b))
    return float(res.statistic), float(res.pvalue)


def wasserstein(a: Sequence[float], b: Sequence[float]) -> float:
    """1-D Wasserstein (earth-mover) distance between two score distributions.

    Unlike KS (a max gap), Wasserstein measures how far the whole distribution
    must move, so it captures the *size* of a leniency shift, not just its presence.
    """
    return float(sps.wasserstein_distance(list(a), list(b)))


def mean_bias(judge: Sequence[float], human: Sequence[float]) -> float:
    """Mean(judge) - mean(human): positive means the judge scores higher than
    humans on average (leniency / score inflation)."""
    j = np.asarray(list(judge), dtype=float); h = np.asarray(list(human), dtype=float)
    return float(j.mean() - h.mean())


def cohens_d(a: Sequence[float], b: Sequence[float]) -> float:
    """Standardized mean difference (mean(a)-mean(b)) / pooled SD. A scale-free
    effect size for how far a judge's scores sit from the human scores."""
    a = np.asarray(list(a), dtype=float); b = np.asarray(list(b), dtype=float)
    na, nb = a.size, b.size
    sp = math.sqrt(((na - 1) * a.var(ddof=1) + (nb - 1) * b.var(ddof=1)) / max(na + nb - 2, 1))
    return float((a.mean() - b.mean()) / sp) if sp > 0 else 0.0
