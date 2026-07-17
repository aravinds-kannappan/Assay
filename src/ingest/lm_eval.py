"""Adapter for lm-evaluation-harness ``--log_samples`` output.

lm-eval writes one JSON object per eval item. Field names drift across tasks
and versions, so this adapter is defensive: it looks for the score under a set
of known metric keys and the cluster key under a set of known grouping fields,
and it fails loudly if it can find no score at all (a silent zero would produce
a confidently wrong confidence interval, the exact failure mode Assay exists to
prevent).

This is a pragmatic subset, not a byte-exact reimplementation of every lm-eval
schema version. The production adapter pins conformance fixtures per harness
release; see docs/ for the compatibility matrix plan.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from ..schema import SampleRecord, prompt_hash

# Metric keys lm-eval commonly emits per sample, in priority order.
_METRIC_KEYS = ("exact_match", "acc", "acc_norm", "em", "correct", "pass", "score")
# Fields that commonly carry a shared-source grouping (the cluster key).
_CLUSTER_FIELDS = ("subject", "category", "source", "passage_id", "group", "task")


def _coerce_binary(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, list) and v:
        return _coerce_binary(v[0])
    return None


def _extract_score(obj: dict, metric: Optional[str]) -> tuple[float, str]:
    if metric is not None:
        if metric not in obj:
            raise KeyError(f"requested metric {metric!r} not found in sample keys {sorted(obj)[:12]}")
        s = _coerce_binary(obj[metric])
        if s is None:
            raise ValueError(f"metric {metric!r} is not numeric: {obj[metric]!r}")
        return s, metric
    for k in _METRIC_KEYS:
        if k in obj:
            s = _coerce_binary(obj[k])
            if s is not None:
                return s, k
    nested = obj.get("metrics")
    if isinstance(nested, dict):
        for k in _METRIC_KEYS:
            if k in nested:
                s = _coerce_binary(nested[k])
                if s is not None:
                    return s, k
    raise KeyError(
        "no score found; looked for "
        f"{_METRIC_KEYS} at top level and under 'metrics'. Keys present: {sorted(obj)[:12]}"
    )


def _extract_id(obj: dict, i: int) -> str:
    for k in ("doc_id", "id", "idx", "question_id"):
        if k in obj and obj[k] is not None:
            return str(obj[k])
    return str(i)


def _extract_cluster(obj: dict, cluster_field: Optional[str]) -> Optional[str]:
    doc = obj.get("doc") if isinstance(obj.get("doc"), dict) else obj
    if cluster_field:
        if cluster_field in doc and doc[cluster_field] is not None:
            return str(doc[cluster_field])
        if cluster_field in obj and obj[cluster_field] is not None:
            return str(obj[cluster_field])
        return None
    for k in _CLUSTER_FIELDS:
        if isinstance(doc, dict) and k in doc and doc[k] is not None:
            return str(doc[k])
    return None


def _extract_prompt_hash(obj: dict) -> Optional[str]:
    for k in ("arguments", "prompt", "rendered_prompt", "doc"):
        if k in obj and obj[k] is not None:
            return prompt_hash(obj[k])
    return None


def load_lm_eval_samples(
    path: str,
    metric: Optional[str] = None,
    cluster_field: Optional[str] = None,
    model: Optional[str] = None,
    dataset: Optional[str] = None,
    harness_version: Optional[str] = None,
) -> list[SampleRecord]:
    """Load an lm-eval samples JSONL file into normalized records.

    ``metric`` / ``cluster_field`` pin the score and grouping columns when
    auto-detection would be ambiguous. Raises on the first line that has no
    recoverable score.
    """
    records: list[SampleRecord] = []
    with open(path, "r", encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{i + 1}: not valid JSON ({e})") from e
            score, metric_name = _extract_score(obj, metric)
            records.append(
                SampleRecord(
                    item_id=_extract_id(obj, i),
                    score=score,
                    cluster_key=_extract_cluster(obj, cluster_field),
                    prompt_sha256=_extract_prompt_hash(obj),
                    model=model or obj.get("model_name") or obj.get("model"),
                    dataset=dataset or obj.get("task") or obj.get("dataset"),
                    harness="lm-eval",
                    harness_version=harness_version or obj.get("git_hash"),
                    metric=metric_name,
                )
            )
    if not records:
        raise ValueError(f"{path}: no samples parsed")
    return records
