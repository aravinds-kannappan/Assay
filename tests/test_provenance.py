import json
from pathlib import Path

import pytest

from assay.check import check_samples
from assay.ingest import load_lm_eval_samples
from assay.provenance import Provenance, assert_all_tagged, tagged

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_tagged_shape():
    node = tagged(0.62, Provenance.DETERMINISTIC, unit="accuracy")
    assert node == {"value": 0.62, "provenance": "deterministic", "unit": "accuracy"}


def test_assert_all_tagged_accepts_tagged_report():
    report = {
        "n": 100,  # allowed bare (a count)
        "accuracy": tagged(0.62, Provenance.DETERMINISTIC),
        "nested": {"se": tagged(0.01, Provenance.STATISTICAL)},
        "flag": True,  # booleans are flags, allowed
    }
    assert_all_tagged(report)  # should not raise


def test_assert_all_tagged_rejects_bare_number():
    report = {"accuracy": 0.62}  # bare float under a non-allowed key
    with pytest.raises(ValueError):
        assert_all_tagged(report)


def test_assert_all_tagged_rejects_bad_provenance():
    report = {"x": {"value": 1.0, "provenance": "vibes"}}
    with pytest.raises(ValueError):
        assert_all_tagged(report)


def test_check_report_is_fully_tagged():
    # The CI-enforced discipline: a real check report passes the walker.
    records = load_lm_eval_samples(EXAMPLES / "sample_lm_eval.jsonl", cluster_field="subject")
    report = check_samples(records)
    assert_all_tagged(report)  # would raise if any number were untagged
    assert report["clustered"]["se_inflation"]["provenance"] == "statistically estimated"
    assert report["accuracy"]["provenance"] == "deterministic"
