"""The unified per-sample schema.

Every adapter (lm-eval, Inspect AI, HELM) normalizes into ``SampleRecord``.
Capturing the rendered-prompt hash, seed, harness version, and dataset
revision on every row is what makes downstream numbers replayable and lets
Assay diff one harness against another.

Parquet I/O is optional: if pyarrow is not installed, records round-trip
through JSONL instead, so the core stats path has no heavy dependency.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional

FIELDS = (
    "item_id",           # stable id of the eval item
    "score",             # per-item outcome, 0.0/1.0 for binary metrics
    "cluster_key",       # shared-source group (MMLU subject, DROP passage, SWE repo)
    "prompt_sha256",     # hash of the rendered prompt: the replay key
    "model",             # model identifier as reported by the harness
    "base_model_family", # de-duplicated lineage, for leakage-aware IRT splits
    "seed",              # decoding seed if reported
    "harness",           # "lm-eval" | "inspect" | "helm"
    "harness_version",   # pinned; unknown versions fail loudly upstream
    "dataset",           # benchmark name
    "dataset_revision",  # HF revision / commit, so relabels are detectable
    "metric",            # the metric name the score came from
)


@dataclass(slots=True)
class SampleRecord:
    item_id: str
    score: float
    cluster_key: Optional[str] = None
    prompt_sha256: Optional[str] = None
    model: Optional[str] = None
    base_model_family: Optional[str] = None
    seed: Optional[int] = None
    harness: Optional[str] = None
    harness_version: Optional[str] = None
    dataset: Optional[str] = None
    dataset_revision: Optional[str] = None
    metric: Optional[str] = None
    extra: dict = field(default_factory=dict)

    def to_row(self) -> dict:
        row = {k: getattr(self, k) for k in FIELDS}
        row["extra"] = json.dumps(self.extra, sort_keys=True) if self.extra else ""
        return row


def prompt_hash(rendered_prompt: Any) -> str:
    """Deterministic SHA256 of a rendered prompt (str or JSON-able object)."""
    if not isinstance(rendered_prompt, str):
        rendered_prompt = json.dumps(rendered_prompt, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(rendered_prompt.encode("utf-8")).hexdigest()


def scores(records: Iterable[SampleRecord]) -> list[float]:
    return [float(r.score) for r in records]


def cluster_keys(records: Iterable[SampleRecord]) -> list[Optional[str]]:
    return [r.cluster_key for r in records]


def has_clusters(records: Iterable[SampleRecord]) -> bool:
    keys = {r.cluster_key for r in records}
    keys.discard(None)
    return len(keys) > 1


# ---- optional parquet I/O -------------------------------------------------

def _pyarrow():
    try:
        import pyarrow  # noqa: F401
        import pyarrow.parquet  # noqa: F401
        return pyarrow
    except Exception:  # pragma: no cover - exercised only when pyarrow present
        return None


def write_parquet(records: list[SampleRecord], path: str) -> str:
    """Write records to parquet if pyarrow is available, else JSONL.

    Returns the actual path written (may swap ``.parquet`` for ``.jsonl``).
    """
    pa = _pyarrow()
    if pa is None:
        if path.endswith(".parquet"):
            path = path[: -len(".parquet")] + ".jsonl"
        with open(path, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r.to_row(), ensure_ascii=False) + "\n")
        return path
    import pyarrow.parquet as pq

    rows = [r.to_row() for r in records]
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path)
    return path
