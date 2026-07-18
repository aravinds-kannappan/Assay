"""Run the full LLM-judge validation study with your own API key.

This is what the 3-item pilot in results/judge/ was a preview of. Point it at any
OpenAI-compatible endpoint and it runs every (item x model x ordering) judgment,
writes the verdicts, and validates each judge against the human labels with
assay.stats. Scale N up to whatever your budget allows.

Setup:
    export ASSAY_JUDGE_BASE_URL=https://your-endpoint        # e.g. Baseten inference URL
    export ASSAY_JUDGE_API_KEY=sk-...
    python scripts/run_judge_study.py --items items.jsonl --n 50 --out results/judge_full

`items.jsonl`: one JSON object per line with keys
    prompt, response_a, response_b, human_winner ("A"|"B"), and optionally cluster.

Output: <out>/verdicts.jsonl and <out>/report.json. Re-run scripts/analyze_judge.py
style analysis, or read report.json directly.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from assay.judge import OpenAICompatibleBackend, judge_pairwise, validate_judge

# The 10-model, 7-provider panel from the pilot. Edit freely.
PANEL = [
    "openai/gpt-oss-120b",
    "nvidia/Nemotron-120B-A12B",
    "zai-org/GLM-4.7",
    "moonshotai/Kimi-K2.5",
    "zai-org/GLM-5",
    "deepseek-ai/DeepSeek-V4-Pro",
    "moonshotai/Kimi-K2.7-Code",
    "thinkingmachines/inkling",
    "zai-org/GLM-5.2",
    "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B",
]


def main() -> None:
    ap = argparse.ArgumentParser(description="run the full LLM-judge study")
    ap.add_argument("--items", required=True, help="JSONL with prompt/response_a/response_b/human_winner")
    ap.add_argument("--n", type=int, default=50, help="number of items to use")
    ap.add_argument("--out", default="results/judge_full")
    ap.add_argument("--models", nargs="*", default=PANEL)
    ap.add_argument("--max-tokens", type=int, default=2048, help="raise for reasoning models")
    ap.add_argument("--no-reasoning", action="store_true", help="omit reasoning_effort")
    args = ap.parse_args()

    items = [json.loads(l) for l in open(args.items) if l.strip()][: args.n]
    backend = OpenAICompatibleBackend()  # reads ASSAY_JUDGE_BASE_URL / ASSAY_JUDGE_API_KEY
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    reff = None if args.no_reasoning else "low"
    verdicts = []
    for idx, it in enumerate(items):
        item_id = it.get("id", f"item{idx}")
        for model in args.models:
            row = {"item_id": item_id, "human": it["human_winner"], "model": model,
                   "cluster": it.get("cluster"),
                   "len_a": len(it["response_a"]), "len_b": len(it["response_b"])}
            for order in ("AB", "BA"):
                try:
                    v = judge_pairwise(it["prompt"], it["response_a"], it["response_b"],
                                       model=model, backend=backend, item_id=item_id, order=order,
                                       max_tokens=args.max_tokens, reasoning_effort=reff or "low",
                                       with_reasoning=False)
                    row[f"pref_{order.lower()}"] = v.preferred
                except Exception as e:  # a judge that will not answer is a finding, not a crash
                    row[f"pref_{order.lower()}"] = None
                    row.setdefault("errors", []).append(f"{order}:{type(e).__name__}")
            verdicts.append(row)
        print(f"  item {idx + 1}/{len(items)} done", flush=True)

    with open(out / "verdicts.jsonl", "w") as fh:
        for r in verdicts:
            fh.write(json.dumps(r) + "\n")

    # Validate each judge against the human labels.
    report = {"n_items": len(items), "models": {}}
    for model in args.models:
        rows = [r for r in verdicts if r["model"] == model
                and r.get("pref_ab") and r.get("pref_ba")]
        if not rows:
            continue
        human = [r["human"] for r in rows]
        ab = [r["pref_ab"] for r in rows]
        ba = [r["pref_ba"] for r in rows]
        clusters = [r["cluster"] for r in rows] if all(r.get("cluster") for r in rows) else None
        la = [r["len_a"] for r in rows]; lb = [r["len_b"] for r in rows]
        rep = validate_judge(human, ab, ba, model=model, clusters=clusters, len_a=la, len_b=lb)
        report["models"][model] = {
            "n": rep.n_items, "agreement": round(rep.agreement_rate, 3),
            "cohens_kappa": round(rep.cohens_kappa, 3), "kappa_ci": [round(x, 3) for x in rep.kappa_ci],
            "position_bias_rate": None if rep.position_bias_rate is None else round(rep.position_bias_rate, 3),
            "length_correlation": None if rep.length_correlation is None else round(rep.length_correlation, 3),
            "mde": round(rep.mde, 4), "items_needed": rep.items_needed,
        }
    json.dump(report, open(out / "report.json", "w"), indent=2)
    print(f"wrote {out}/verdicts.jsonl and {out}/report.json for {len(args.models)} judges over {len(items)} items")


if __name__ == "__main__":
    main()
