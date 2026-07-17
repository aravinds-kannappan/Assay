"""Provenance tagging.

Assay's core discipline: every number a report emits carries exactly one
provenance tag, so no value ever claims more than its method supports.

  deterministic          a fixed computation (a regex, a parse, an accuracy count)
  statistically estimated an estimate with sampling uncertainty (an SE, an MDE, a p-value)
  trained-model           an output of a model fit by gradient descent (IRT ability, a classifier score)
  LLM-judged              an output produced by prompting a language model

``assert_all_tagged`` is wired into the test suite so the discipline is
machine-enforced rather than left to author diligence.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Mapping


class Provenance(str, Enum):
    DETERMINISTIC = "deterministic"
    STATISTICAL = "statistically estimated"
    TRAINED = "trained-model"
    LLM_JUDGED = "LLM-judged"


def tagged(value: Any, provenance: Provenance | str, **meta: Any) -> dict:
    """Wrap a value with its provenance tag and optional metadata.

    >>> tagged(0.62, Provenance.DETERMINISTIC, unit="accuracy")
    {'value': 0.62, 'provenance': 'deterministic', 'unit': 'accuracy'}
    """
    prov = Provenance(provenance).value
    node = {"value": value, "provenance": prov}
    node.update(meta)
    return node


def _is_tagged_node(obj: Any) -> bool:
    return isinstance(obj, Mapping) and "value" in obj and not _looks_like_container(obj)


def _looks_like_container(obj: Mapping) -> bool:
    # A tagged node has a scalar-ish "value"; a plain dict that merely happens
    # to contain a "value" key with a dict/list under it is treated as a container.
    v = obj.get("value")
    return isinstance(v, (Mapping, list))


def assert_all_tagged(report: Any, _path: str = "report") -> None:
    """Raise if any numeric leaf in ``report`` is missing a provenance tag.

    Walks nested dicts and lists. A "tagged node" is any mapping with a
    scalar ``value`` key; it must also carry a valid ``provenance``. Bare
    ints/floats sitting directly under a dict key are treated as untagged
    metadata only when the key is in ``_ALLOWED_BARE`` (counts, sizes, config).
    """
    if _is_tagged_node(report):
        prov = report.get("provenance")
        if prov not in {p.value for p in Provenance}:
            raise ValueError(f"{_path}: value {report['value']!r} has invalid provenance {prov!r}")
        return
    if isinstance(report, Mapping):
        for k, v in report.items():
            # Booleans are flags, not measurements, so they never need a tag.
            if isinstance(v, (int, float)) and not isinstance(v, bool) and k not in _ALLOWED_BARE:
                raise ValueError(
                    f"{_path}.{k}: bare number {v!r} is missing a provenance tag "
                    f"(wrap it with assay.provenance.tagged, or add the key to _ALLOWED_BARE)"
                )
            assert_all_tagged(v, f"{_path}.{k}")
    elif isinstance(report, list):
        for i, v in enumerate(report):
            assert_all_tagged(v, f"{_path}[{i}]")


# Keys allowed to hold a bare number: they are configuration or exact counts,
# not measurements, so they need no provenance tag.
_ALLOWED_BARE = frozenset({
    "n", "n_items", "n_clusters", "n_models", "count", "size", "alpha", "power",
    "seed", "b_only", "c_only", "n_discordant", "strict_hits", "flexible_hits",
    "df", "k", "index", "min_clusters",
})
