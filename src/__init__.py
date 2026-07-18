"""Assay: the noise floor for LLM evals.

An analytical-chemistry take on eval measurement. Assay ingests the per-sample
logs your harness already writes and turns bare point estimates into
decision-grade measurements: clustered error bars, cluster-aware paired tests, a
pre-flight minimum-detectable-effect gate, and a cross-harness reconciler that
pins a score gap on the exact rule that caused it.

Every number Assay reports carries one of four provenance tags:
deterministic, statistically estimated, trained-model, or LLM-judged.
"""
from __future__ import annotations

__version__ = "0.1.0"

from . import check, gate, irt, judge, provenance, schema, stats
from .gate import run_gate
from .ingest import load_lm_eval_samples
from .irt import fit_2pl
from .judge import judge_pairwise, panel_verdict, reconcile_judges, run_panel, validate_judge
from .reconcile import reconcile_gsm8k

__all__ = [
    "__version__",
    "check",
    "gate",
    "irt",
    "judge",
    "provenance",
    "schema",
    "stats",
    "load_lm_eval_samples",
    "reconcile_gsm8k",
    "run_gate",
    "fit_2pl",
    "judge_pairwise",
    "validate_judge",
    "reconcile_judges",
    "panel_verdict",
    "run_panel",
]
