import json
from pathlib import Path

import numpy as np
import pytest

from assay import irt

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _pearson(x, y):
    return float(np.corrcoef(x, y)[0, 1])


def test_parameter_recovery_on_simulated_data():
    # The core validation: fit data simulated from KNOWN 2PL parameters and check
    # that the recovered parameters correlate strongly with the truth.
    rng = np.random.default_rng(0)
    M, I = 120, 200
    theta = rng.normal(0, 1, M)
    b = rng.normal(0, 1.2, I)
    a = np.exp(rng.normal(0, 0.4, I))
    Y, mask = irt.simulate_2pl(theta, a, b, seed=1)

    fit = irt.fit_2pl(Y, mask)
    assert fit.converged
    # Ability and difficulty recover with high correlation; discrimination is
    # noisier but still clearly positive.
    assert _pearson(fit.theta, theta) > 0.9
    assert _pearson(fit.b, b) > 0.9
    assert _pearson(fit.a, a) > 0.5


def test_recovery_on_shipped_fixture():
    Y = np.asarray([[float(x) for x in json.loads(l)["scores"]]
                    for l in open(EXAMPLES / "irt_outcomes.jsonl") if l.strip()])
    truth = json.load(open(EXAMPLES / "irt_truth.json"))
    fit = irt.fit_2pl(Y)
    assert _pearson(fit.theta, np.array(truth["theta"])) > 0.85
    assert _pearson(fit.b, np.array(truth["b"])) > 0.85


def test_item_information_peaks_at_difficulty():
    # A single item's Fisher information is maximized when ability == difficulty.
    a = np.array([1.5]); b = np.array([0.3])
    grid = np.linspace(-3, 3, 601)
    info = np.array([irt.item_information(t, a, b)[0] for t in grid])
    assert grid[np.argmax(info)] == pytest.approx(0.3, abs=0.02)


def test_higher_discrimination_more_information():
    lo = irt.item_information(0.0, np.array([0.5]), np.array([0.0]))[0]
    hi = irt.item_information(0.0, np.array([2.0]), np.array([0.0]))[0]
    assert hi > lo


def test_fast_subset_beats_random_reconstruction():
    # A Fisher-selected subset should estimate held-out ability better than a
    # random subset of the same size.
    rng = np.random.default_rng(3)
    M, I = 80, 160
    theta = rng.normal(0, 1, M)
    b = rng.normal(0, 1.2, I)
    a = np.exp(rng.normal(0, 0.4, I))
    Y, _ = irt.simulate_2pl(theta, a, b, seed=4)
    fit = irt.fit_2pl(Y)

    k = 30
    smart = irt.select_fast_subset(fit.a, fit.b, k)
    randi = rng.choice(I, size=k, replace=False)

    def rmse(idx):
        errs = []
        for m in range(M):
            th, _ = irt.estimate_ability(Y[m, idx], fit.a[idx], fit.b[idx])
            errs.append((th - fit.theta[m]) ** 2)
        return float(np.sqrt(np.mean(errs)))

    assert rmse(smart) < rmse(randi)


def test_estimate_ability_orders_models():
    rng = np.random.default_rng(9)
    I = 200
    b = rng.normal(0, 1, I); a = np.exp(rng.normal(0, 0.3, I))
    strong, _ = irt.simulate_2pl(np.array([1.5]), a, b, seed=1)
    weak, _ = irt.simulate_2pl(np.array([-1.5]), a, b, seed=2)
    th_strong, _ = irt.estimate_ability(strong[0], a, b)
    th_weak, _ = irt.estimate_ability(weak[0], a, b)
    assert th_strong > th_weak


def test_missing_entries_are_ignored():
    rng = np.random.default_rng(5)
    theta = rng.normal(0, 1, 60); b = rng.normal(0, 1, 100); a = np.exp(rng.normal(0, 0.3, 100))
    Y, mask = irt.simulate_2pl(theta, a, b, seed=6, missing=0.3)
    fit = irt.fit_2pl(Y, mask)  # must run despite 30% missing
    assert fit.converged
    assert _pearson(fit.theta, theta) > 0.8
