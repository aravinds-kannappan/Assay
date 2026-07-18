"""Reproduce the judge-pilot report and figures from committed verdicts.

The raw verdicts (results/judge/verdicts.jsonl) were collected by calling 10 live
models through an OpenAI-compatible endpoint with assay.judge; that collection
needs an API key and is not rerun here. This script recomputes every statistic and
figure from the committed verdicts, so the ANALYSIS is fully reproducible offline.

    python scripts/analyze_judge.py
"""
import json
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

from assay import stats

ROOT = Path(__file__).resolve().parent.parent
JD = ROOT / "results" / "judge"
FIGS = ROOT / "results" / "figures"
DOCS = ROOT / "docs" / "figures"
for d in (FIGS, DOCS):
    d.mkdir(parents=True, exist_ok=True)

INK, TEAL, MUTED, WARN, CRIT, GRID = "#10171C", "#0C8C7E", "#63727C", "#B26E12", "#C24248", "#D6DDD9"
plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white", "axes.edgecolor": MUTED,
    "axes.labelcolor": INK, "text.color": INK, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "font.size": 10.5,
    "axes.titlesize": 12, "axes.titleweight": "bold", "figure.dpi": 150, "savefig.bbox": "tight",
    "axes.spines.top": False, "axes.spines.right": False,
})

rows = [json.loads(l) for l in open(JD / "verdicts.jsonl") if l.strip()]
items = {"it0": "A", "it2": "A", "it5": "B"}   # human winners for the 3 pilot items
MODELS = list(dict.fromkeys(r["model"] for r in rows))
SHORT = {"openai/gpt-oss-120b": "gpt-oss-120b", "nvidia/Nemotron-120B-A12B": "Nemotron-Super",
         "zai-org/GLM-4.7": "GLM-4.7", "moonshotai/Kimi-K2.5": "Kimi-K2.5", "zai-org/GLM-5": "GLM-5",
         "deepseek-ai/DeepSeek-V4-Pro": "DeepSeek-V4-Pro", "moonshotai/Kimi-K2.7-Code": "Kimi-K2.7-Code",
         "thinkingmachines/inkling": "inkling", "zai-org/GLM-5.2": "GLM-5.2",
         "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B": "Nemotron-Ultra"}
PROVIDER = {"openai/gpt-oss-120b": "OpenAI", "nvidia/Nemotron-120B-A12B": "NVIDIA", "zai-org/GLM-4.7": "Z.ai",
            "moonshotai/Kimi-K2.5": "Moonshot", "zai-org/GLM-5": "Z.ai", "deepseek-ai/DeepSeek-V4-Pro": "DeepSeek",
            "moonshotai/Kimi-K2.7-Code": "Moonshot", "thinkingmachines/inkling": "Thinking Machines",
            "zai-org/GLM-5.2": "Z.ai", "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B": "NVIDIA"}


def cell(it, m):
    r = next(x for x in rows if x["item_id"] == it and x["model"] == m)
    return r["pref_ab"], r["pref_ba"]


def final(ab, ba):
    if ab and ba:
        return ab if ab == ba else "tie"
    return ab or ba


report = {"design": {"items": list(items), "human_winners": items, "n_models": len(MODELS),
                     "providers": sorted(set(PROVIDER.values())), "orderings": ["AB", "BA"]},
          "note": "N=3 pilot on real Chatbot Arena items with 10 live models (7 providers). "
                  "Demonstrates the pipeline end to end; at N=3 the judge-ranking statistics are "
                  "deliberately underpowered (see kappa CI). The assay.judge module runs the full study.",
          "models": {}}
cons, human_ag, labels, final_matrix = [], [], [], {}
for m in MODELS:
    both = consistent = decisive = agree = 0
    fin = {}
    for it, human in items.items():
        ab, ba = cell(it, m)
        f = final(ab, ba); fin[it] = f
        if ab and ba:
            both += 1
            consistent += (ab == ba)
        if f in ("A", "B"):
            decisive += 1
            agree += (f == human)
    final_matrix[m] = fin
    cr = consistent / both if both else float("nan")
    hr = agree / decisive if decisive else float("nan")
    cons.append(cr); human_ag.append(hr); labels.append(SHORT[m])
    report["models"][m] = {"provider": PROVIDER[m], "n_both_orderings": both,
                           "order_consistency_rate": round(cr, 3),
                           "position_bias_rate": round(1 - cr, 3) if both else None,
                           "n_decisive": decisive,
                           "human_agreement_rate": round(hr, 3) if decisive else None}

pooled_j, pooled_h, pooled_cl = [], [], []
for m in MODELS:
    for it, human in items.items():
        f = final_matrix[m][it]
        if f in ("A", "B"):
            pooled_j.append(f); pooled_h.append(human); pooled_cl.append(it)
agree = stats.agreement_rate(pooled_j, pooled_h)
kappa = stats.cohens_kappa(pooled_j, pooled_h)
lo, hi, se = stats.kappa_bootstrap_ci(pooled_j, pooled_h, clusters=pooled_cl, n_boot=4000)
report["pooled"] = {"n_decisive_judgments": len(pooled_j), "human_agreement_rate": round(agree, 3),
                    "cohens_kappa": round(kappa, 3), "kappa_ci95_item_clustered": [round(lo, 3), round(hi, 3)],
                    "kappa_se": round(se, 3),
                    "reading": "the kappa CI is enormous: N=3 cannot rank these judges. That is the point, "
                               "assay.judge reports the item budget you actually need."}
report["headline_findings"] = [
    "9 of 10 judges were 100% order-consistent on the items they completed; Nemotron-Super flipped its "
    "verdict when A/B order swapped on 2 of 3 items (33% consistent), a clear position-bias outlier.",
    "Structured-output reliability varied: 3 judges emitted non-standard JSON keys (better/choice/"
    "better_response) despite a json_schema; 2 reasoning judges returned null on the hardest item under a "
    "600-token cap, fixed by raising max_tokens to 2048.",
    "Judges mostly agreed with each other and the human on the two clear items and split on the "
    "letter-uniqueness puzzle: real disagreement, correctly surfaced.",
]
json.dump(report, open(JD / "judge_report.json", "w"), indent=2)

# Figure J1: per-model order-consistency (position bias)
order = np.argsort(cons)
fig, ax = plt.subplots(figsize=(7.6, 4.6))
cols = [CRIT if cons[i] < 0.5 else (WARN if cons[i] < 1 else TEAL) for i in order]
ax.barh([labels[i] for i in order], [cons[i] * 100 for i in order], color=cols)
for j, i in enumerate(order):
    ax.text(cons[i] * 100 + 2, j, f"{cons[i]*100:.0f}%", va="center", fontsize=9, color=MUTED)
ax.set_xlim(0, 112); ax.set_xlabel("order-consistency rate (AB verdict == BA verdict)")
ax.set_title("Position bias: does the judge flip when A/B order swaps?  (N=3 pilot)")
ax.grid(axis="y", visible=False)
for folder in (FIGS, DOCS):
    fig.savefig(folder / "figJ1_position_bias.png", dpi=150)
plt.close(fig)

# Figure J2: judge-judge agreement heatmap
M = len(MODELS)
mat = np.full((M, M), np.nan)
for i, mi in enumerate(MODELS):
    for j, mj in enumerate(MODELS):
        pairs = [(final_matrix[mi][it], final_matrix[mj][it]) for it in items
                 if final_matrix[mi][it] in ("A", "B") and final_matrix[mj][it] in ("A", "B")]
        if pairs:
            mat[i, j] = sum(1 for a, b in pairs if a == b) / len(pairs)
fig, ax = plt.subplots(figsize=(7.8, 6.6))
im = ax.imshow(mat, cmap="BrBG", vmin=0, vmax=1)
ax.set_xticks(range(M)); ax.set_yticks(range(M))
ax.set_xticklabels([SHORT[m] for m in MODELS], rotation=45, ha="right", fontsize=8)
ax.set_yticklabels([SHORT[m] for m in MODELS], fontsize=8)
for i in range(M):
    for j in range(M):
        if not np.isnan(mat[i, j]):
            ax.text(j, i, f"{mat[i, j]:.1f}", ha="center", va="center",
                    color="white" if abs(mat[i, j] - 0.5) > 0.35 else INK, fontsize=7)
ax.set_title("Judge-judge agreement on final verdicts  (N=3 pilot)")
fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="agreement")
ax.grid(False)
for folder in (FIGS, DOCS):
    fig.savefig(folder / "figJ2_judge_agreement.png", dpi=150)
plt.close(fig)

print(f"models {len(MODELS)} | items {len(items)} | decisive judgments {len(pooled_j)}")
print(f"pooled human agreement {agree*100:.0f}% | kappa {kappa:+.2f} CI95 [{lo:+.2f},{hi:+.2f}]")
print("wrote judge_report.json, figJ1_position_bias.png, figJ2_judge_agreement.png")
