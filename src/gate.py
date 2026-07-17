"""The significance gate.

Given two aligned sets of per-item scores (a baseline checkpoint and a candidate),
decide whether the candidate's claimed gain is real, inside the noise floor, or a
regression, and say exactly how many items it would take to resolve the claim.

This is the logic behind the `assay gate` GitHub Action: it annotates a PR with a
verdict instead of letting a 200-item eval's 2-point wobble read as progress.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Optional, Sequence

import numpy as np

from . import stats


@dataclass
class GateResult:
    n: int
    acc_baseline: float
    acc_candidate: float
    delta: float               # candidate - baseline
    mde: float                 # paired minimum detectable effect at this n
    p_value: float
    test: str
    significant: bool
    verdict: str               # one of the VERDICT_* strings
    items_needed: Optional[int]  # to resolve the observed |delta|, None if already resolvable
    sigma_diff: float
    alpha: float
    power: float

    def to_dict(self) -> dict:
        return asdict(self)


VERDICT_IMPROVE = "significant improvement"
VERDICT_REGRESS = "significant regression"
VERDICT_UNDERPOWERED = "underpowered: delta below the noise floor"
VERDICT_INCONCLUSIVE = "not significant"


def run_gate(
    baseline: Sequence[float],
    candidate: Sequence[float],
    clusters: Optional[Sequence] = None,
    alpha: float = 0.05,
    power: float = 0.8,
) -> GateResult:
    """Compare two checkpoints on the same items and return a verdict."""
    a = np.asarray(list(baseline), dtype=float)
    c = np.asarray(list(candidate), dtype=float)
    if a.shape != c.shape:
        raise ValueError(f"baseline ({a.size}) and candidate ({c.size}) differ in length")
    n = a.size
    delta = float(c.mean() - a.mean())

    if clusters is not None and len({k for k in clusters}) > 1:
        paired = stats.paired_clustered(a, c, list(clusters))
    else:
        paired = stats.paired_mcnemar(a, c)

    d = c - a
    sigma_diff = float(d.std(ddof=1)) if n > 1 else float("nan")
    # A degenerate all-agree case has sigma 0; fall back to the discordant-rate SD.
    if not sigma_diff or math.isnan(sigma_diff) or sigma_diff == 0:
        disagree = float(np.mean(d != 0))
        sigma_diff = math.sqrt(max(disagree, 1e-6))
    mde = stats.mde_paired(n, sigma_diff, alpha=alpha, power=power)

    significant = paired.p_value < alpha
    if significant and delta > 0:
        verdict = VERDICT_IMPROVE
    elif significant and delta < 0:
        verdict = VERDICT_REGRESS
    elif abs(delta) < mde:
        verdict = VERDICT_UNDERPOWERED
    else:
        verdict = VERDICT_INCONCLUSIVE

    items_needed = None
    if not significant and abs(delta) > 0:
        items_needed = stats.required_n(abs(delta), sigma_diff, alpha=alpha, power=power)

    return GateResult(
        n=n, acc_baseline=float(a.mean()), acc_candidate=float(c.mean()),
        delta=delta, mde=mde, p_value=paired.p_value, test=paired.test,
        significant=significant, verdict=verdict, items_needed=items_needed,
        sigma_diff=sigma_diff, alpha=alpha, power=power,
    )


def _badge(result: GateResult) -> str:
    return {
        VERDICT_IMPROVE: "PASS",
        VERDICT_REGRESS: "REGRESSION",
        VERDICT_UNDERPOWERED: "UNDERPOWERED",
        VERDICT_INCONCLUSIVE: "INCONCLUSIVE",
    }[result.verdict]


def render_markdown(result: GateResult, title: str = "Assay significance gate") -> str:
    """A PR-comment-ready markdown block summarizing the verdict."""
    r = result
    lines = [
        f"### {title}: **{_badge(r)}**",
        "",
        f"> {r.verdict}",
        "",
        "| metric | value |",
        "| --- | --- |",
        f"| baseline accuracy | {r.acc_baseline*100:.2f}% |",
        f"| candidate accuracy | {r.acc_candidate*100:.2f}% |",
        f"| claimed delta | {r.delta*100:+.2f} pts |",
        f"| minimum detectable effect (n={r.n}) | {r.mde*100:.2f} pts |",
        f"| paired test | {r.test}, p = {r.p_value:.3g} |",
    ]
    if r.items_needed is not None:
        lines.append(f"| items needed to resolve this delta | ~{r.items_needed:,} |")
    lines += [
        "",
        (f"The claimed **{r.delta*100:+.2f} pt** change is smaller than the "
         f"**{r.mde*100:.2f} pt** this {r.n}-item eval can resolve. "
         "Add items or pair more comparisons before trusting it."
         if r.verdict == VERDICT_UNDERPOWERED else
         f"Decision computed at alpha={r.alpha}, power={r.power}."),
        "",
        "_deterministic gate over a statistically estimated paired test (assay)_",
    ]
    return "\n".join(lines)
