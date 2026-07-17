"""GSM8K strict-vs-flexible reconciliation.

Given one *frozen* set of model generations (the model never re-runs), score
them two ways and attribute every point of the accuracy gap to the extraction
rule responsible. This is the deterministic core of the reconciler: it needs no
GPU, reruns in under a second, and shows that the harness, not the model, moved
the number.

The two systems being compared here are two *scorers*, so the strict-vs-flexible
delta is itself testable with the same paired machinery used for two models.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .extractors import flexible_extract, normalize_number, strict_match


@dataclass
class Flip:
    item_id: str
    gold: Optional[str]
    strict_pred: Optional[str]
    flexible_pred: Optional[str]
    strict_correct: bool
    flexible_correct: bool
    reason: str


@dataclass
class ReconcileResult:
    n: int
    strict_hits: int
    flexible_hits: int
    strict_acc: float
    flexible_acc: float
    delta: float                      # flexible_acc - strict_acc
    flips: list[Flip] = field(default_factory=list)
    strict_scores: list[float] = field(default_factory=list)
    flexible_scores: list[float] = field(default_factory=list)

    @property
    def flexible_recovered(self) -> int:
        """Items flexible got right that strict missed."""
        return sum(1 for f in self.flips if f.flexible_correct and not f.strict_correct)

    @property
    def flexible_fooled(self) -> int:
        """Items flexible got wrong that strict got right (the honest downside)."""
        return sum(1 for f in self.flips if f.strict_correct and not f.flexible_correct)


def _reason(strict_correct, flexible_correct, sp, fp, gold) -> str:
    if flexible_correct and not strict_correct:
        if sp is None:
            return "no '####' delimiter emitted; strict-match found nothing, flexible recovered the trailing number"
        return f"strict extracted '{sp}' (wrong); flexible extracted '{fp}' (correct)"
    if strict_correct and not flexible_correct:
        return f"flexible grabbed trailing distractor '{fp}'; strict matched the delimited answer '{sp}'"
    return ""


def reconcile_gsm8k(records: Iterable[dict]) -> ReconcileResult:
    """Reconcile frozen GSM8K generations.

    Each record needs ``gold`` and ``completion`` (and optionally ``id``).
    Returns per-scorer accuracies, the delta, an attribution list of flips,
    and per-item 0/1 vectors for downstream paired testing.
    """
    flips: list[Flip] = []
    strict_scores: list[float] = []
    flexible_scores: list[float] = []
    strict_hits = 0
    flexible_hits = 0
    n = 0

    for i, r in enumerate(records):
        n += 1
        gold = normalize_number(str(r["gold"]))
        text = r["completion"]
        sp = strict_match(text)
        fp = flexible_extract(text)
        sc = sp is not None and sp == gold
        fc = fp is not None and fp == gold
        strict_hits += int(sc)
        flexible_hits += int(fc)
        strict_scores.append(1.0 if sc else 0.0)
        flexible_scores.append(1.0 if fc else 0.0)
        if sc != fc:
            flips.append(
                Flip(
                    item_id=str(r.get("id", i)),
                    gold=gold,
                    strict_pred=sp,
                    flexible_pred=fp,
                    strict_correct=sc,
                    flexible_correct=fc,
                    reason=_reason(sc, fc, sp, fp, gold),
                )
            )

    if n == 0:
        raise ValueError("no records to reconcile")
    strict_acc = strict_hits / n
    flexible_acc = flexible_hits / n
    return ReconcileResult(
        n=n,
        strict_hits=strict_hits,
        flexible_hits=flexible_hits,
        strict_acc=strict_acc,
        flexible_acc=flexible_acc,
        delta=flexible_acc - strict_acc,
        flips=flips,
        strict_scores=strict_scores,
        flexible_scores=flexible_scores,
    )
