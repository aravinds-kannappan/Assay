"""The ``assay`` command-line interface.

    assay check     <samples.jsonl>              error bars + MDE on ingested logs
    assay reconcile gsm8k <frozen.jsonl>         attribute a strict/flexible gap
    assay power     --n N --p P                  minimum detectable effect for a design
    assay gate      <baseline.jsonl> <cand.jsonl>  significance verdict for a PR
    assay irt       fit <matrix>                 fit a 2PL model, report fast subsets
    assay version
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

import numpy as np

from . import __version__
from .check import check_samples, format_report
from .gate import render_markdown, run_gate
from .ingest import load_lm_eval_samples
from .reconcile import reconcile_gsm8k
from .stats import mde_absolute, paired_mcnemar, required_n


def _read_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise SystemExit(f"{path}:{i + 1}: not valid JSON ({e})")
    return rows


def cmd_check(args: argparse.Namespace) -> int:
    records = load_lm_eval_samples(args.samples, metric=args.metric, cluster_field=args.cluster_field)
    report = check_samples(records, alpha=args.alpha, power=args.power)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"assay check  ::  {args.samples}")
        print(format_report(report))
    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    if args.benchmark != "gsm8k":
        raise SystemExit(f"only 'gsm8k' is implemented in v{__version__}; got {args.benchmark!r}")
    res = reconcile_gsm8k(_read_jsonl(args.frozen))
    paired = paired_mcnemar(res.strict_scores, res.flexible_scores)
    if args.json:
        print(json.dumps({
            "n": res.n, "strict_acc": res.strict_acc, "flexible_acc": res.flexible_acc,
            "delta": res.delta, "flexible_recovered": res.flexible_recovered,
            "flexible_fooled": res.flexible_fooled, "paired_p_value": paired.p_value,
            "flips": [vars(f) for f in res.flips],
        }, indent=2))
        return 0
    print(f"assay reconcile gsm8k  ::  {args.frozen}")
    print(f"  frozen generations : {res.n}  (the model never re-ran)")
    print(f"  strict-match       : {res.strict_acc * 100:6.2f}%   [deterministic]")
    print(f"  flexible-extract   : {res.flexible_acc * 100:6.2f}%   [deterministic]")
    print(f"  delta              : {res.delta * 100:+6.2f} pts  attributed to the extraction rule")
    print(f"  flexible recovered : {res.flexible_recovered}  (strict missed the '####' delimiter)")
    print(f"  flexible fooled    : {res.flexible_fooled}  (grabbed a trailing distractor)")
    print(f"  paired McNemar p   : {paired.p_value:.4g}  [statistically estimated]")
    print("  verdict            : the harness moved the number, not the model")
    if res.flips and args.show_flips:
        print(f"\n  attribution (first {min(len(res.flips), args.show_flips)}):")
        for f in res.flips[: args.show_flips]:
            print(f"    [{f.item_id}] gold={f.gold} strict={f.strict_pred} flexible={f.flexible_pred}")
            print(f"        -> {f.reason}")
    return 0


def cmd_power(args: argparse.Namespace) -> int:
    m = mde_absolute(args.n, args.p, alpha=args.alpha, power=args.power)
    print(f"assay power  ::  n={args.n}, p={args.p}, alpha={args.alpha}, power={args.power}")
    print(f"  minimum detectable effect : {m * 100:.2f} pts  [statistically estimated]")
    if args.claim is not None:
        import math
        sigma = math.sqrt(max(args.p * (1 - args.p), 1e-12))
        need = required_n(args.claim, sigma, alpha=args.alpha, power=args.power)
        verdict = "RESOLVABLE" if args.claim >= m else "UNDERPOWERED"
        print(f"  claimed effect            : {args.claim * 100:.2f} pts  -> {verdict}")
        if verdict == "UNDERPOWERED":
            print(f"  items needed for claim    : ~{need}  (unpaired; pairing cuts this substantially)")
    return 0


def _aligned_scores(baseline_path, candidate_path, metric, cluster_field):
    """Load two samples files and align them by item_id."""
    base = load_lm_eval_samples(baseline_path, metric=metric, cluster_field=cluster_field)
    cand = load_lm_eval_samples(candidate_path, metric=metric, cluster_field=cluster_field)
    cmap = {r.item_id: r for r in cand}
    a, c, clusters = [], [], []
    dropped = 0
    for r in base:
        if r.item_id in cmap:
            a.append(r.score)
            c.append(cmap[r.item_id].score)
            clusters.append(r.cluster_key)
        else:
            dropped += 1
    if not a:
        raise SystemExit("no shared item_ids between baseline and candidate")
    has_clusters = len({k for k in clusters if k is not None}) > 1
    return a, c, (clusters if has_clusters else None), dropped


def cmd_gate(args: argparse.Namespace) -> int:
    a, c, clusters, dropped = _aligned_scores(args.baseline, args.candidate, args.metric, args.cluster_field)
    result = run_gate(a, c, clusters=clusters, alpha=args.alpha, power=args.power)
    md = render_markdown(result)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"assay gate  ::  {args.baseline}  vs  {args.candidate}")
        if dropped:
            print(f"  ! {dropped} baseline items had no candidate match and were dropped")
        print(f"  baseline / candidate : {result.acc_baseline*100:.2f}%  ->  {result.acc_candidate*100:.2f}%")
        print(f"  delta                : {result.delta*100:+.2f} pts")
        print(f"  MDE @ n={result.n:<5}      : {result.mde*100:.2f} pts   [statistically estimated]")
        print(f"  paired test          : {result.test}, p = {result.p_value:.3g}")
        print(f"  VERDICT              : {result.verdict.upper()}")
        if result.items_needed is not None:
            print(f"  items to resolve it  : ~{result.items_needed:,}")

    if args.md:
        with open(args.md, "w", encoding="utf-8") as fh:
            fh.write(md + "\n")

    # GitHub Actions integration: step summary + machine-readable outputs.
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if args.github and summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(md + "\n")
    out = os.environ.get("GITHUB_OUTPUT")
    if args.github and out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"verdict={result.verdict}\n")
            fh.write(f"delta_pts={result.delta*100:.3f}\n")
            fh.write(f"mde_pts={result.mde*100:.3f}\n")
            fh.write(f"significant={'true' if result.significant else 'false'}\n")

    underpowered = result.verdict.startswith("underpowered")
    regression = result.verdict.startswith("significant regression")
    if (args.fail_on_underpowered and underpowered) or (args.fail_on_regression and regression):
        return 1
    return 0


def _load_matrix(path: str) -> np.ndarray:
    """Load a (models x items) 0/1 matrix from .npy or a JSONL of {'scores': [...]}"""
    if path.endswith(".npy"):
        return np.load(path).astype(float)
    return np.asarray([[float(x) for x in obj["scores"]] for obj in _read_jsonl(path)], dtype=float)


def cmd_irt(args: argparse.Namespace) -> int:
    from . import irt  # local import keeps the numpy-only fast path lean

    Y = _load_matrix(args.matrix)
    fit = irt.fit_2pl(Y)
    print(f"assay irt fit  ::  {args.matrix}")
    print(f"  models x items : {fit.n_models} x {fit.n_items}")
    print(f"  converged      : {fit.converged}   log-likelihood {fit.loglik:.1f}   [trained-model]")
    print(f"  ability theta  : mean {fit.theta.mean():+.3f}, sd {fit.theta.std():.3f}")
    print(f"  discrimination : median a {np.median(fit.a):.3f}")
    print(f"  difficulty     : range b [{fit.b.min():+.2f}, {fit.b.max():+.2f}]")
    if args.subset:
        idx = irt.select_fast_subset(fit.a, fit.b, min(args.subset, fit.n_items))
        print(f"  fast subset ({len(idx)} items, most Fisher information): {[int(i) for i in idx]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="assay", description="the noise floor for LLM evals")
    p.add_argument("--version", action="version", version=f"assay {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("check", help="error bars + MDE on ingested per-sample logs")
    c.add_argument("samples")
    c.add_argument("--metric", default=None)
    c.add_argument("--cluster-field", default=None)
    c.add_argument("--alpha", type=float, default=0.05)
    c.add_argument("--power", type=float, default=0.8)
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_check)

    r = sub.add_parser("reconcile", help="attribute a score gap to the code that caused it")
    r.add_argument("benchmark", choices=["gsm8k"])
    r.add_argument("frozen")
    r.add_argument("--show-flips", type=int, default=8)
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_reconcile)

    pw = sub.add_parser("power", help="minimum detectable effect for a design")
    pw.add_argument("--n", type=int, required=True)
    pw.add_argument("--p", type=float, default=0.5)
    pw.add_argument("--claim", type=float, default=None)
    pw.add_argument("--alpha", type=float, default=0.05)
    pw.add_argument("--power", type=float, default=0.8)
    pw.set_defaults(func=cmd_power)

    g = sub.add_parser("gate", help="significance verdict comparing two checkpoints")
    g.add_argument("baseline")
    g.add_argument("candidate")
    g.add_argument("--metric", default=None)
    g.add_argument("--cluster-field", default=None)
    g.add_argument("--alpha", type=float, default=0.05)
    g.add_argument("--power", type=float, default=0.8)
    g.add_argument("--md", default=None, help="write a markdown verdict to this path")
    g.add_argument("--github", action="store_true", help="write to GITHUB_STEP_SUMMARY / GITHUB_OUTPUT")
    g.add_argument("--fail-on-underpowered", action="store_true")
    g.add_argument("--fail-on-regression", action="store_true")
    g.add_argument("--json", action="store_true")
    g.set_defaults(func=cmd_gate)

    it = sub.add_parser("irt", help="fit a 2PL item response model")
    it.add_argument("action", choices=["fit"])
    it.add_argument("matrix", help="(models x items) matrix: .npy or JSONL of {'scores': [...]}")
    it.add_argument("--subset", type=int, default=0, help="print a Fisher-information fast subset of this size")
    it.set_defaults(func=cmd_irt)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
