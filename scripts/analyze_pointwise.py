"""Distributional analysis of pointwise LLM-judge scores vs human ratings.

Each of 10 judges rated 80 HelpSteer2 responses on the SAME 0-4 helpfulness scale
the human annotators used. This script measures, per judge, how far the judge's
score distribution sits from the human one:
  - mean bias (leniency): mean(judge) - mean(human)
  - Wasserstein distance and a two-sample KS test (distributions differ?)
  - Spearman/Pearson correlation (does the judge at least rank-agree with humans?)
  - Cohen's d (standardized shift)
and draws the distribution overlay, calibration curves, and per-judge shift.

Writes results/judge_pointwise/report.json + explorer_pointwise.json (+ docs copy)
and 4 figures. Data-driven: rerun after more chunks land.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

from assay import stats

ROOT = Path(__file__).resolve().parent.parent
CH = ROOT / "results" / "judge_pointwise" / "chunks"
OUT = ROOT / "results" / "judge_pointwise"
FIGS = ROOT / "results" / "figures"; FIGS.mkdir(parents=True, exist_ok=True)
DOCS_FIGS = ROOT / "docs" / "figures"; DOCS_FIGS.mkdir(parents=True, exist_ok=True)
DOCS = ROOT / "docs"
ITEMS = {it["item_id"]: it for it in json.load(open(OUT / "items.json"))}

INK, TEAL, MUTED, WARN, CRIT, GRID, VIOLET = "#10171C", "#0C8C7E", "#63727C", "#B26E12", "#C24248", "#D6DDD9", "#7C5CD0"
plt.rcParams.update({"figure.facecolor": "white", "axes.facecolor": "white", "axes.edgecolor": MUTED,
    "axes.labelcolor": INK, "text.color": INK, "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.8, "font.size": 10.5, "axes.titlesize": 12, "axes.titleweight": "bold",
    "figure.dpi": 150, "savefig.bbox": "tight", "axes.spines.top": False, "axes.spines.right": False})

def short(m): return m.split("/")[-1]
def save(fig, name):
    for d in (FIGS, DOCS_FIGS): fig.savefig(d / name, dpi=150)


def load():
    rows = []
    for f in sorted(glob.glob(str(CH / "chunk_*.jsonl"))):
        for l in open(f):
            l = l.strip()
            if not l: continue
            try:
                r = json.loads(l)
                if r.get("item_id") in ITEMS and isinstance(r.get("score"), int):
                    rows.append(r)
            except Exception:
                pass
    return rows


def main():
    rows = load()
    models = sorted({r["model"] for r in rows})
    items = sorted({r["item_id"] for r in rows})
    by = {(r["item_id"], r["model"]): r for r in rows}
    n = len(items)
    print(f"loaded {len(rows)} scored rows | {n} items | {len(models)} judges")

    per = {}
    for m in models:
        pairs = [(by[(i, m)]["score"], ITEMS[i]["human_helpfulness"]) for i in items if (i, m) in by]
        if len(pairs) < 3: continue
        js = [p[0] for p in pairs]; hs = [p[1] for p in pairs]
        ks_stat, ks_p = stats.ks_test(js, hs)
        sp_r, sp_p = stats.spearman(js, hs)
        per[m] = {
            "n": len(pairs), "mean_judge": round(float(np.mean(js)), 3), "mean_human": round(float(np.mean(hs)), 3),
            "mean_bias": round(stats.mean_bias(js, hs), 3), "wasserstein": round(stats.wasserstein(js, hs), 3),
            "ks_stat": round(ks_stat, 3), "ks_p": round(ks_p, 4), "cohens_d": round(stats.cohens_d(js, hs), 3),
            "spearman_r": round(sp_r, 3), "spearman_p": round(sp_p, 4),
            "dist": [int(np.sum(np.array(js) == k)) for k in range(5)],
        }

    human_scores = [ITEMS[i]["human_helpfulness"] for i in items]
    pooled_judge = [by[(i, m)]["score"] for i in items for m in models if (i, m) in by]
    pooled_bias = float(np.mean(pooled_judge) - np.mean(human_scores))
    ks_all = stats.ks_test(pooled_judge, human_scores)
    report = {"n_items": n, "n_judges": len(models),
              "human_mean": round(float(np.mean(human_scores)), 3),
              "pooled_judge_mean": round(float(np.mean(pooled_judge)), 3),
              "pooled_mean_bias": round(pooled_bias, 3),
              "pooled_ks_stat": round(ks_all[0], 3), "pooled_ks_p": round(ks_all[1], 6),
              "human_dist": [int(np.sum(np.array(human_scores) == k)) for k in range(5)],
              "pooled_judge_dist": [int(np.sum(np.array(pooled_judge) == k)) for k in range(5)],
              "per_model": per,
              "provenance": "scores [LLM-judged] vs human [dataset]; shift stats [statistically estimated]"}
    json.dump(report, open(OUT / "report.json", "w"), indent=2)

    # explorer: per item, human score + each judge's score + reasoning
    ex = []
    for i in items:
        it = ITEMS[i]
        judges = [{"model": short(m), "score": by[(i, m)]["score"], "reason": (by[(i, m)].get("reasoning") or "")[:220]}
                  for m in models if (i, m) in by]
        ex.append({"item_id": i, "prompt": it["prompt"][:600], "response": it["response"][:900],
                   "human_helpfulness": it["human_helpfulness"],
                   "judge_mean": round(float(np.mean([j["score"] for j in judges])), 2) if judges else None,
                   "judges": judges})
    payload = {"n_items": n, "models": [short(m) for m in models], "pooled_mean_bias": round(pooled_bias, 3), "items": ex}
    json.dump(payload, open(OUT / "explorer_pointwise.json", "w"))
    json.dump(payload, open(DOCS / "judge_pointwise.json", "w"))

    x = np.arange(5)
    # Fig A: distribution overlay (the shift)
    hd = np.array(report["human_dist"]) / max(sum(report["human_dist"]), 1)
    jd = np.array(report["pooled_judge_dist"]) / max(sum(report["pooled_judge_dist"]), 1)
    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    ax.bar(x - 0.2, hd, 0.4, label=f"human (mean {report['human_mean']})", color=MUTED)
    ax.bar(x + 0.2, jd, 0.4, label=f"LLM judges (mean {report['pooled_judge_mean']})", color=TEAL)
    ax.set_xticks(x); ax.set_xlabel("helpfulness score (0-4)"); ax.set_ylabel("share of ratings")
    ax.set_title(f"Distribution shift: judges are lenient (+{report['pooled_mean_bias']:.2f} vs human, KS p={ks_all[1]:.1e})")
    ax.legend(frameon=False); ax.grid(axis="x", visible=False)
    save(fig, "fig_pw_distribution.png"); plt.close(fig)

    # Fig B: calibration curves (mean judge score at each human level)
    fig, ax = plt.subplots(figsize=(7.6, 4.6))
    ax.plot([0, 4], [0, 4], color=CRIT, ls="--", lw=1.3, label="perfect calibration")
    for m in models:
        ys = []
        for h in range(5):
            sc = [by[(i, m)]["score"] for i in items if (i, m) in by and ITEMS[i]["human_helpfulness"] == h]
            ys.append(np.mean(sc) if sc else np.nan)
        ax.plot(range(5), ys, marker="o", lw=1.4, alpha=0.75, label=short(m))
    ax.set_xlabel("human helpfulness (0-4)"); ax.set_ylabel("mean judge score")
    ax.set_title("Calibration: judges compress toward high scores")
    ax.legend(frameon=False, fontsize=7, ncol=2, loc="lower right")
    save(fig, "fig_pw_calibration.png"); plt.close(fig)

    # Fig C: per-judge leniency (mean bias) + Wasserstein
    order = sorted(per, key=lambda m: per[m]["mean_bias"])
    fig, ax = plt.subplots(figsize=(7.6, 4.6))
    biases = [per[m]["mean_bias"] for m in order]
    cols = [CRIT if b >= 1.0 else (WARN if b >= 0.5 else TEAL) for b in biases]
    ax.barh([short(m) for m in order], biases, color=cols)
    for i, m in enumerate(order):
        ax.text(biases[i] + 0.02, i, f"W={per[m]['wasserstein']:.2f}", va="center", fontsize=8, color=MUTED)
    ax.axvline(0, color=INK, lw=1)
    ax.set_xlabel("mean bias  (judge mean - human mean; >0 = lenient)")
    ax.set_title("Every judge scores higher than humans (leniency)")
    ax.grid(axis="y", visible=False); save(fig, "fig_pw_leniency.png"); plt.close(fig)

    # Fig D: rank agreement (Spearman) despite the shift
    order2 = sorted(per, key=lambda m: per[m]["spearman_r"])
    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    rs = [per[m]["spearman_r"] for m in order2]
    ax.barh([short(m) for m in order2], rs, color=TEAL)
    for i, m in enumerate(order2):
        sig = "*" if per[m]["spearman_p"] < 0.05 else ""
        ax.text(rs[i] + 0.01, i, f"{rs[i]:.2f}{sig}", va="center", fontsize=8, color=MUTED)
    ax.set_xlabel("Spearman rank correlation with human scores  (* p<0.05)")
    ax.set_title("Judges rank-agree with humans even while over-scoring")
    ax.grid(axis="y", visible=False); save(fig, "fig_pw_rankcorr.png"); plt.close(fig)

    print(f"pooled judge mean {report['pooled_judge_mean']} vs human {report['human_mean']} "
          f"(bias +{report['pooled_mean_bias']}, KS p={ks_all[1]:.2e})")
    biasrange = [round(min(v['mean_bias'] for v in per.values()), 2), round(max(v['mean_bias'] for v in per.values()), 2)]
    corrrange = [round(min(v['spearman_r'] for v in per.values()), 2), round(max(v['spearman_r'] for v in per.values()), 2)]
    print(f"per-judge mean bias {biasrange} | Spearman-r {corrrange}")
    print("wrote report.json, explorer_pointwise.json, 4 figures")


if __name__ == "__main__":
    main()
