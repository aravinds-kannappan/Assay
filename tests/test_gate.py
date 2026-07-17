import json
from pathlib import Path

import pytest

from assay.gate import (
    VERDICT_IMPROVE,
    VERDICT_REGRESS,
    VERDICT_UNDERPOWERED,
    render_markdown,
    run_gate,
)
from assay.ingest import load_lm_eval_samples

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _load(path, cluster="task"):
    return load_lm_eval_samples(path, cluster_field=cluster)


def _aligned(base, cand):
    cmap = {r.item_id: r for r in cand}
    a, c, cl = [], [], []
    for r in base:
        if r.item_id in cmap:
            a.append(r.score); c.append(cmap[r.item_id].score); cl.append(r.cluster_key)
    return a, c, cl


def test_gate_fixture_is_underpowered():
    base = _load(EXAMPLES / "gate_baseline.jsonl")
    cand = _load(EXAMPLES / "gate_candidate.jsonl")
    a, c, cl = _aligned(base, cand)
    res = run_gate(a, c, clusters=cl)
    assert res.n == 200
    assert res.delta == pytest.approx(0.02, abs=1e-9)   # exactly +2 pts by construction
    assert res.verdict == VERDICT_UNDERPOWERED
    assert res.mde > abs(res.delta)                      # delta is inside the noise floor
    assert res.items_needed and res.items_needed > 200   # need more items to resolve it
    assert res.test == "clustered-paired-z"              # cluster key present


def test_gate_detects_real_improvement():
    # A large, unambiguous gain over many items must come back significant.
    a = [0] * 200
    c = [1] * 60 + [0] * 140  # +30 pts
    res = run_gate(a, c)
    assert res.verdict == VERDICT_IMPROVE
    assert res.significant and res.p_value < 0.05


def test_gate_detects_regression():
    a = [1] * 60 + [0] * 140
    c = [0] * 200  # -30 pts
    res = run_gate(a, c)
    assert res.verdict == VERDICT_REGRESS
    assert res.delta < 0


def test_gate_length_mismatch_raises():
    with pytest.raises(ValueError):
        run_gate([1, 0, 1], [1, 0])


def test_markdown_contains_verdict_and_numbers():
    a = [0] * 200
    c = [1] * 5 + [0] * 195  # +2.5 pts, underpowered
    res = run_gate(a, c)
    md = render_markdown(res)
    assert "Assay significance gate" in md
    assert "minimum detectable effect" in md
    assert "%" in md and "pts" in md


def test_gate_json_roundtrip():
    res = run_gate([1, 0, 1, 1, 0], [1, 1, 1, 0, 0])
    d = res.to_dict()
    assert set(["n", "delta", "mde", "p_value", "verdict"]).issubset(d)
    json.dumps(d)  # must be serializable
