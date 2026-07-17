"""The ``assay`` command-line interface.

    assay check   <samples.jsonl>   error bars + MDE on ingested per-sample logs
    assay reconcile gsm8k <frozen.jsonl>   attribute the strict/flexible gap
    assay power   --n N --p P        minimum detectable effect for a design
    assay version
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from . import __version__
from .check import check_samples, format_report
from .ingest import load_lm_eval_samples
from .reconcile import reconcile_gsm8k
from .stats import mde_absolute, paired_clustered, paired_mcnemar, required_n


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
    records = load_lm_eval_samples(
        args.samples, metric=args.metric, cluster_field=args.cluster_field
    )
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
    rows = _read_jsonl(args.frozen)
    res = reconcile_gsm8k(rows)
    paired = paired_mcnemar(res.strict_scores, res.flexible_scores)

    if args.json:
        print(json.dumps({
            "n": res.n,
            "strict_acc": res.strict_acc,
            "flexible_acc": res.flexible_acc,
            "delta": res.delta,
            "flexible_recovered": res.flexible_recovered,
            "flexible_fooled": res.flexible_fooled,
            "paired_p_value": paired.p_value,
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
        print("\n  attribution (first {}):".format(min(len(res.flips), args.show_flips)))
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="assay", description="the noise floor for LLM evals")
    p.add_argument("--version", action="version", version=f"assay {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("check", help="error bars + MDE on ingested per-sample logs")
    c.add_argument("samples", help="lm-eval --log_samples JSONL file")
    c.add_argument("--metric", default=None, help="score column to use (auto-detect if omitted)")
    c.add_argument("--cluster-field", default=None, help="grouping field for clustered SEs")
    c.add_argument("--alpha", type=float, default=0.05)
    c.add_argument("--power", type=float, default=0.8)
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_check)

    r = sub.add_parser("reconcile", help="attribute a score gap to the code that caused it")
    r.add_argument("benchmark", choices=["gsm8k"])
    r.add_argument("frozen", help="frozen generations JSONL (fields: gold, completion)")
    r.add_argument("--show-flips", type=int, default=8, help="print up to N attributed flips")
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_reconcile)

    pw = sub.add_parser("power", help="minimum detectable effect for a design")
    pw.add_argument("--n", type=int, required=True, help="number of items")
    pw.add_argument("--p", type=float, default=0.5, help="assumed accuracy (default 0.5, worst case)")
    pw.add_argument("--claim", type=float, default=None, help="claimed effect to test (e.g. 0.02)")
    pw.add_argument("--alpha", type=float, default=0.05)
    pw.add_argument("--power", type=float, default=0.8)
    pw.set_defaults(func=cmd_power)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
