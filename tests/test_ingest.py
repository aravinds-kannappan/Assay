import json
from pathlib import Path

import pytest

from assay.ingest import load_lm_eval_samples
from assay.schema import has_clusters

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_load_sample_file():
    records = load_lm_eval_samples(EXAMPLES / "sample_lm_eval.jsonl", cluster_field="subject")
    assert len(records) == 48
    assert all(r.score in (0.0, 1.0) for r in records)
    assert all(r.cluster_key is not None for r in records)
    assert has_clusters(records)
    assert {r.cluster_key for r in records} == {
        "abstract_algebra", "anatomy", "astronomy",
        "college_chemistry", "world_religions", "virology",
    }


def test_metric_autodetect_finds_acc():
    records = load_lm_eval_samples(EXAMPLES / "sample_lm_eval.jsonl")
    assert all(r.metric == "acc" for r in records)


def test_prompt_hash_is_captured():
    records = load_lm_eval_samples(EXAMPLES / "sample_lm_eval.jsonl")
    assert all(r.prompt_sha256 and len(r.prompt_sha256) == 64 for r in records)


def test_missing_score_fails_loudly(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"doc_id": 0, "doc": {"subject": "x"}}) + "\n")
    with pytest.raises(KeyError):
        load_lm_eval_samples(str(bad))


def test_invalid_json_fails_loudly(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not json}\n")
    with pytest.raises(ValueError):
        load_lm_eval_samples(str(bad))


def test_explicit_metric_missing_raises(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text(json.dumps({"doc_id": 0, "acc": 1}) + "\n")
    with pytest.raises(KeyError):
        load_lm_eval_samples(str(f), metric="exact_match")
