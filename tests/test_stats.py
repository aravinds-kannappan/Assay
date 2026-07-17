import math

import numpy as np
import pytest

from assay import stats


def test_naive_se_matches_formula():
    x = [1, 1, 1, 0, 0]  # p = 0.6
    mean, se = stats.mean_and_naive_se(x)
    assert mean == pytest.approx(0.6)
    # sample std / sqrt(n), ddof=1
    assert se == pytest.approx(math.sqrt(np.var(x, ddof=1) / 5))


def test_z_factor_known_value():
    # (1.95996 + 0.84162) at alpha=0.05, power=0.8
    assert stats.z_factor(0.05, 0.8) == pytest.approx(2.8016, abs=1e-3)


def test_cr2_with_singleton_clusters_equals_naive():
    # Bell-McCaffrey CR2 for the mean reduces exactly to the naive SE when every
    # item is its own cluster. This is a strong correctness check on the formula.
    rng = np.random.default_rng(0)
    x = rng.integers(0, 2, size=40).astype(float)
    clusters = list(range(40))
    cse = stats.cluster_robust_se(x, clusters, method="CR2")
    _, naive = stats.mean_and_naive_se(x)
    assert cse.cluster_se == pytest.approx(naive, rel=1e-9)


def test_clustered_se_exceeds_naive_when_correlated():
    # Whole clusters move together -> clustered SE must be much larger than naive.
    scores = [1] * 10 + [0] * 10 + [1] * 10 + [0] * 10
    clusters = ["a"] * 10 + ["b"] * 10 + ["c"] * 10 + ["d"] * 10
    cse = stats.cluster_robust_se(scores, clusters, method="CR2")
    assert cse.inflation > 2.0
    assert cse.small_cluster_warning is True  # only 4 clusters


def test_cr_ordering_cr0_le_cr2():
    scores = [1] * 8 + [0] * 8 + [1] * 6 + [0] * 2
    clusters = ["a"] * 8 + ["b"] * 8 + ["c"] * 8
    cr0 = stats.cluster_robust_se(scores, clusters, method="CR0").cluster_se
    cr2 = stats.cluster_robust_se(scores, clusters, method="CR2").cluster_se
    assert cr2 >= cr0  # bias reduction inflates, never shrinks


def test_cluster_bootstrap_close_to_cr2():
    scores = [1] * 8 + [0] * 8 + [1] * 7 + [0] * 1 + [1] * 2 + [0] * 6
    clusters = ["a"] * 8 + ["b"] * 8 + ["c"] * 8 + ["d"] * 8
    cr2 = stats.cluster_robust_se(scores, clusters, method="CR2").cluster_se
    boot = stats.cluster_bootstrap_se(scores, clusters, n_boot=3000, seed=1)
    assert boot == pytest.approx(cr2, rel=0.35)  # same order of magnitude


def test_cluster_bootstrap_is_deterministic():
    scores = [1, 0, 1, 1, 0, 0, 1, 0]
    clusters = ["a", "a", "b", "b", "c", "c", "d", "d"]
    a = stats.cluster_bootstrap_se(scores, clusters, n_boot=500, seed=7)
    b = stats.cluster_bootstrap_se(scores, clusters, n_boot=500, seed=7)
    assert a == b


def test_paired_mcnemar_strong_effect():
    a = [0] * 10
    b = [1] * 10
    res = stats.paired_mcnemar(a, b)
    assert res.b_only == 0 and res.c_only == 10
    assert res.p_value < 0.01
    assert res.delta == pytest.approx(1.0)


def test_paired_mcnemar_no_effect():
    a = [1, 0, 1, 0]
    b = [1, 0, 1, 0]
    res = stats.paired_mcnemar(a, b)
    assert res.n_discordant == 0
    assert res.p_value == 1.0


def test_paired_clustered_uses_clusters():
    # Same per-item differences, but clustering changes the SE and hence p.
    a = [0, 0, 0, 0, 1, 1, 1, 1]
    b = [1, 1, 1, 1, 1, 1, 1, 1]
    clusters = ["x", "x", "x", "x", "y", "y", "y", "y"]
    res = stats.paired_clustered(a, b, clusters, method="CR2")
    assert res.test == "clustered-paired-z"
    assert res.delta == pytest.approx(0.5)
    assert 0.0 <= res.p_value <= 1.0


def test_mde_and_required_n_roundtrip():
    n = 500
    p = 0.5
    m = stats.mde_absolute(n, p)
    sigma = math.sqrt(p * (1 - p))
    n_back = stats.required_n(m, sigma)
    assert n_back == pytest.approx(n, abs=2)


def test_mde_decreases_with_n():
    assert stats.mde_absolute(1000, 0.5) < stats.mde_absolute(100, 0.5)


def test_mde_absolute_known_value():
    # 2.8016 * 0.5 / sqrt(200) ~= 0.09905
    assert stats.mde_absolute(200, 0.5) == pytest.approx(0.0990, abs=1e-3)


def test_holm_step_down():
    reject = stats.holm([0.01, 0.04, 0.03], alpha=0.05)
    assert reject == [True, False, False]


def test_holm_all_reject_when_tiny():
    reject = stats.holm([0.0001, 0.0002, 0.0003], alpha=0.05)
    assert all(reject)


def test_cluster_robust_rejects_none_key():
    with pytest.raises(ValueError):
        stats.cluster_robust_se([1, 0, 1], [None, "a", "b"])
