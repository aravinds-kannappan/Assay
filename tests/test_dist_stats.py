import numpy as np
import pytest

from assay import stats


def test_ks_same_distribution_not_rejected():
    rng = np.random.default_rng(0)
    a = rng.normal(0, 1, 500); b = rng.normal(0, 1, 500)
    stat, p = stats.ks_test(a, b)
    assert p > 0.05  # same distribution -> do not reject


def test_ks_shifted_distribution_rejected():
    rng = np.random.default_rng(1)
    a = rng.normal(0, 1, 500); b = rng.normal(2, 1, 500)
    stat, p = stats.ks_test(a, b)
    assert p < 0.01 and stat > 0.3


def test_wasserstein_zero_for_identical():
    assert stats.wasserstein([1, 2, 3], [1, 2, 3]) == pytest.approx(0.0)


def test_wasserstein_equals_shift_for_translation():
    # Shifting every point by 2 gives a Wasserstein distance of exactly 2.
    assert stats.wasserstein([0, 1, 2, 3], [2, 3, 4, 5]) == pytest.approx(2.0)


def test_mean_bias_sign():
    # judge scores higher than human -> positive leniency bias
    assert stats.mean_bias([4, 4, 3], [2, 2, 1]) > 0
    assert stats.mean_bias([1, 1], [3, 3]) < 0


def test_cohens_d_direction_and_scale():
    d = stats.cohens_d([5, 4, 5, 4], [1, 2, 1, 2])  # large, positive, non-degenerate
    assert d > 3
    assert stats.cohens_d([1, 2, 3], [1, 2, 3]) == pytest.approx(0.0)  # identical -> 0


def test_pearson_matches_known():
    r, p = stats.pearson([1, 2, 3, 4], [2, 4, 6, 8])  # perfectly linear
    assert r == pytest.approx(1.0)


def test_leniency_end_to_end():
    # A lenient judge (scores 3-4) vs uniform human (0-4): shift is detectable.
    human = list(range(5)) * 8            # uniform 0..4
    judge = ([3, 4] * 20)                 # clustered high
    assert stats.mean_bias(judge, human) > 1.0
    assert stats.ks_test(judge, human)[1] < 0.05
    assert stats.wasserstein(judge, human) > 1.0
