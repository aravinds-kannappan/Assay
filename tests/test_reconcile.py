import json
from pathlib import Path

import pytest

from assay.reconcile import (
    flexible_extract,
    normalize_number,
    reconcile_gsm8k,
    strict_match,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def load(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_normalize_number():
    assert normalize_number("1,024") == "1024"
    assert normalize_number("$5.00") == "5"
    assert normalize_number("3.5") == "3.5"
    assert normalize_number("18.") == "18"
    assert normalize_number("  42 ") == "42"
    assert normalize_number("nope") is None
    assert normalize_number(None) is None


def test_strict_match_requires_delimiter():
    assert strict_match("The total is 42. #### 42") == "42"
    assert strict_match("The answer is 42.") is None
    assert strict_match("wandering 12 then #### 7") == "7"  # last delimiter wins


def test_flexible_takes_last_number():
    assert flexible_extract("the answer is 42") == "42"
    assert flexible_extract("42 dollars over 3 steps") == "3"  # fooled by trailing number
    assert flexible_extract("no numbers here") is None


def test_reconcile_golden_on_fixture():
    # Deterministic golden values for the shipped illustrative fixture.
    rows = load(EXAMPLES / "gsm8k_frozen.jsonl")
    res = reconcile_gsm8k(rows)
    assert res.n == 24
    assert res.strict_hits == 13
    assert res.flexible_hits == 21
    assert res.strict_acc == pytest.approx(13 / 24)
    assert res.flexible_acc == pytest.approx(21 / 24)
    assert res.delta == pytest.approx(8 / 24)
    assert res.flexible_recovered == 10
    assert res.flexible_fooled == 2


def test_reconcile_flip_reasons_are_populated():
    rows = load(EXAMPLES / "gsm8k_frozen.jsonl")
    res = reconcile_gsm8k(rows)
    assert len(res.flips) == res.flexible_recovered + res.flexible_fooled
    for f in res.flips:
        assert f.reason  # every flip carries an attribution string
        assert f.strict_correct != f.flexible_correct


def test_reconcile_scores_feed_paired_test():
    from assay.stats import paired_mcnemar

    rows = load(EXAMPLES / "gsm8k_frozen.jsonl")
    res = reconcile_gsm8k(rows)
    paired = paired_mcnemar(res.strict_scores, res.flexible_scores)
    # 10 recovered vs 2 fooled -> significant at 0.05
    assert paired.p_value < 0.05


def test_reconcile_empty_raises():
    with pytest.raises(ValueError):
        reconcile_gsm8k([])
