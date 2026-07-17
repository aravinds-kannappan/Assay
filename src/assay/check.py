"""Build a decision-grade report from normalized samples.

Turns a list of SampleRecord into a tagged report: point estimate with a
clustered error bar (when a cluster key is present), the SE inflation ratio,
and the minimum detectable effect at the current item count. Every numeric leaf
is wrapped with a provenance tag, and ``assert_all_tagged`` is run before the
report is returned, so an untagged number fails fast.
"""
from __future__ import annotations

from typing import Optional

from . import stats
from .provenance import Provenance, assert_all_tagged, tagged
from .schema import SampleRecord, cluster_keys, has_clusters, scores


def check_samples(
    records: list[SampleRecord],
    alpha: float = 0.05,
    power: float = 0.8,
    cluster_method: str = "CR2",
) -> dict:
    s = scores(records)
    n = len(s)
    mean, naive_se = stats.mean_and_naive_se(s)

    report: dict = {
        "n": n,
        "alpha": alpha,
        "power": power,
        "accuracy": tagged(round(mean, 6), Provenance.DETERMINISTIC, unit="accuracy"),
        "naive_se": tagged(round(naive_se, 6), Provenance.STATISTICAL, kind="clt-se"),
    }

    if has_clusters(records):
        keys = cluster_keys(records)
        cse = stats.cluster_robust_se(s, keys, method=cluster_method)
        lo, hi = cse.ci(alpha)
        report["clustered"] = {
            "n_clusters": cse.n_clusters,
            "method": tagged(cse.method, Provenance.DETERMINISTIC),
            "cluster_se": tagged(round(cse.cluster_se, 6), Provenance.STATISTICAL, kind="cluster-robust-se"),
            "se_inflation": tagged(round(cse.inflation, 4), Provenance.STATISTICAL,
                                   note="cluster_se / naive_se"),
            "ci95": tagged([round(lo, 6), round(hi, 6)], Provenance.STATISTICAL),
            "small_cluster_warning": cse.small_cluster_warning,
        }
        if cse.small_cluster_warning:
            boot = stats.cluster_bootstrap_se(s, keys)
            report["clustered"]["bootstrap_se"] = tagged(
                round(boot, 6), Provenance.STATISTICAL,
                note=f"pairs-cluster bootstrap cross-check ({cse.n_clusters} clusters < 30)")

    # minimum detectable effect at this n (unpaired, worst-case-ish at the observed p)
    report["mde_absolute"] = tagged(
        round(stats.mde_absolute(n, mean, alpha, power), 6),
        Provenance.STATISTICAL,
        note="smallest absolute accuracy gap an unpaired eval of this size can resolve",
    )

    assert_all_tagged(report)
    return report


def format_report(report: dict) -> str:
    """Human-readable rendering of a check report."""
    n = report["n"]
    acc = report["accuracy"]["value"]
    lines = [f"n = {n} items", f"accuracy = {acc:.4f}  [deterministic]"]
    if "clustered" in report:
        c = report["clustered"]
        lo, hi = c["ci95"]["value"]
        lines.append(
            f"clustered SE ({c['method']['value']}, {c['n_clusters']} clusters) = "
            f"{c['cluster_se']['value']:.4f}  [statistically estimated]"
        )
        lines.append(f"  95% CI = [{lo:.4f}, {hi:.4f}]")
        lines.append(f"  SE inflation vs naive = {c['se_inflation']['value']:.2f}x")
        if c.get("small_cluster_warning"):
            b = c.get("bootstrap_se", {}).get("value")
            extra = f"; bootstrap SE cross-check = {b:.4f}" if b is not None else ""
            lines.append(f"  ! only {c['n_clusters']} clusters (<30): CR2 is shaky here{extra}")
    else:
        lines.append(f"naive SE = {report['naive_se']['value']:.4f}  (no cluster key found)")
    lines.append(
        f"minimum detectable effect @ n={n}: {report['mde_absolute']['value'] * 100:.2f} pts"
        f"  (alpha={report['alpha']}, power={report['power']})"
    )
    return "\n".join(lines)
