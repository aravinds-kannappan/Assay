"""Distributional analysis of pointwise LLM-judge scores vs human ratings.

Each judge rated HelpSteer2 responses on the SAME 0-4 helpfulness scale the human
annotators used. Per judge we measure how far the judge's score distribution sits
from the human one:
  - valid_response_rate: fraction of attempts that returned a usable score (a judge
    you cannot parse is not a judge; this is the first gate)
  - mean bias (leniency): mean(judge) - mean(human)
  - Wasserstein distance + two-sample KS test (do the distributions differ?)
  - Spearman/Pearson correlation (does the judge at least rank-agree with humans?)
  - Cohen's d (standardized shift)
Judges below a validity threshold are excluded from the shift stats and flagged.

Writes results/judge_pointwise/report.json + explorer_pointwise.json (+ docs copy)
and 5 figures. Data-driven: rerun after more chunks land.
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
MIN_VALID_RATE = 0.5   # a judge below this is not reliable enough to compare

INK, TEAL, MUTED, WARN, CRIT, GRID, VIOLET = "#10171C", "#0C8C7E", "#63727C", "#B26E12", "#C24248", "#D6DDD9", "#7C5CD0"
plt.rcParams.update({"figure.facecolor": "white", "axes.facecolor": "white", "axes.edgecolor": MUTED,
    "axes.labelcolor": INK, "text.color": INK, "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.8, "font.size": 10.5, "axes.titlesize": 12, "axes.titleweight": "bold",
    "figure.dpi": 150, "savefig.bbox": "tight", "axes.spines.top": False, "axes.spines.right": False})

def short(m): return m.split("/")[-1]
def save(fig, name):
    for d in (FIGS, DOCS_FIGS): fig.savefig(d / name, dpi=150)
def valid_score(v): return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 4


def load():
    rows = []
    for f in sorted(glob.glob(str(CH / "chunk_*.jsonl"))):
        for l in open(f):
            l = l.strip()
            if not l: continue
            try:
                r = json.loads(l)
            except Exception:
                continue
            if r.get("item_id") in ITEMS:
                rows.append(r)
    return rows


def main():
    rows = load()
    models = sorted({r["model"] for r in rows})
    items = sorted({r["item_id"] for r in rows})
    by = {(r["item_id"], r["model"]): r for r in rows}
    # human score comes from the rows (items.json can be sparse); one per item
    human = {}
    for r in rows:
        if r.get("human_helpfulness") is not None:
            human[r["item_id"]] = r["human_helpfulness"]
    items = [i for i in items if i in human]
    n = len(items)
    print(f"loaded {len(rows)} rows | {n} items with human labels | {len(models)} judges")

    # ---- reliability gate: does each judge return a usable score at all? ----
    reliability = {}
    for m in models:
        attempted = sum(1 for i in items if (i, m) in by)
        valid = sum(1 for i in items if (i, m) in by and valid_score(by[(i, m)].get("score")))
        reliability[short(m)] = {"attempted": attempted, "valid": valid,
                                 "valid_response_rate": round(valid / attempted, 3) if attempted else 0.0}
    reliable = [m for m in models if reliability[short(m)]["valid_response_rate"] >= MIN_VALID_RATE]
    excluded = [short(m) for m in models if m not in reliable]

    # ---- distributional shift, reliable judges only ----
    per = {}
    for m in reliable:
        pairs = [(by[(i, m)]["score"], human[i]) for i in items
                 if (i, m) in by and valid_score(by[(i, m)].get("score"))]
        if len(pairs) < 5: continue
        js = [p[0] for p in pairs]; hs = [p[1] for p in pairs]
        ks_stat, ks_p = stats.ks_test(js, hs)
        sp_r, sp_p = stats.spearman(js, hs)
        per[m] = {
            "n": len(pairs), "valid_response_rate": reliability[short(m)]["valid_response_rate"],
            "mean_judge": round(float(np.mean(js)), 3), "mean_human": round(float(np.mean(hs)), 3),
            "mean_bias": round(stats.mean_bias(js, hs), 3), "wasserstein": round(stats.wasserstein(js, hs), 3),
            "ks_stat": round(ks_stat, 3), "ks_p": round(ks_p, 4), "cohens_d": round(stats.cohens_d(js, hs), 3),
            "spearman_r": round(sp_r, 3), "spearman_p": round(sp_p, 4),
            "dist": [int(np.sum(np.array(js) == k)) for k in range(5)],
        }

    human_scores = [human[i] for i in items]
    pooled = [by[(i, m)]["score"] for i in items for m in reliable
              if (i, m) in by and valid_score(by[(i, m)].get("score"))]
    pooled_bias = float(np.mean(pooled) - np.mean(human_scores))
    ks_all = stats.ks_test(pooled, human_scores)
    report = {"n_items": n, "n_judges_total": len(models), "n_judges_reliable": len(per),
              "excluded_judges": excluded, "min_valid_rate": MIN_VALID_RATE,
              "human_mean": round(float(np.mean(human_scores)), 3),
              "pooled_judge_mean": round(float(np.mean(pooled)), 3),
              "pooled_mean_bias": round(pooled_bias, 3),
              "pooled_ks_stat": round(ks_all[0], 3), "pooled_ks_p": round(ks_all[1], 6),
              "human_dist": [int(np.sum(np.array(human_scores) == k)) for k in range(5)],
              "pooled_judge_dist": [int(np.sum(np.array(pooled) == k)) for k in range(5)],
              "reliability": reliability, "per_model": per,
              "provenance": "scores [LLM-judged] vs human [dataset]; shift stats [statistically estimated]"}
    json.dump(report, open(OUT / "report.json", "w"), indent=2)

    # explorer: per item, human score + each judge's score + reasoning
    ex = []
    for i in items:
        it = ITEMS[i]
        judges = [{"model": short(m), "score": by[(i, m)].get("score"),
                   "reason": (by[(i, m)].get("reasoning") or "")[:220]}
                  for m in models if (i, m) in by]
        vs = [j["score"] for j in judges if valid_score(j["score"])]
        ex.append({"item_id": i, "prompt": it["prompt"][:600], "response": it["response"][:900],
                   "human_helpfulness": human[i],
                   "judge_mean": round(float(np.mean(vs)), 2) if vs else None, "judges": judges})
    payload = {"n_items": n, "models": [short(m) for m in reliable], "excluded_judges": excluded,
               "summary": {"human_mean": report["human_mean"], "pooled_judge_mean": report["pooled_judge_mean"],
                           "pooled_mean_bias": round(pooled_bias, 3), "pooled_ks_p": report["pooled_ks_p"],
                           "n_judges_reliable": len(per), "n_judges_total": len(models),
                           "bias_range": [round(min(v["mean_bias"] for v in per.values()), 2),
                                          round(max(v["mean_bias"] for v in per.values()), 2)] if per else [0, 0],
                           "corr_range": [round(min(v["spearman_r"] for v in per.values()), 2),
                                          round(max(v["spearman_r"] for v in per.values()), 2)] if per else [0, 0],
                           "most_lenient": short(max(per, key=lambda m: per[m]["mean_bias"])) if per else None,
                           "worst_reliability": min(reliability, key=lambda k: reliability[k]["valid_response_rate"])},
               "reliability": reliability, "items": ex}
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
    sign = "+" if pooled_bias >= 0 else ""
    ax.set_title(f"Distribution shift: judge mean {sign}{report['pooled_mean_bias']:.2f} vs human (KS p={ks_all[1]:.1e})")
    ax.legend(frameon=False); ax.grid(axis="x", visible=False)
    save(fig, "fig_pw_distribution.png"); plt.close(fig)

    # Fig B: calibration curves (mean judge score at each human level)
    fig, ax = plt.subplots(figsize=(7.6, 4.6))
    ax.plot([0, 4], [0, 4], color=CRIT, ls="--", lw=1.3, label="perfect calibration")
    for m in reliable:
        ys = []
        for h in range(5):
            sc = [by[(i, m)]["score"] for i in items
                  if (i, m) in by and valid_score(by[(i, m)].get("score")) and human[i] == h]
            ys.append(np.mean(sc) if sc else np.nan)
        ax.plot(range(5), ys, marker="o", lw=1.4, alpha=0.75, label=short(m))
    ax.set_xlabel("human helpfulness (0-4)"); ax.set_ylabel("mean judge score")
    ax.set_title("Calibration: where do judges place each human score level?")
    ax.legend(frameon=False, fontsize=7, ncol=2, loc="lower right")
    save(fig, "fig_pw_calibration.png"); plt.close(fig)

    # Fig C: per-judge leniency (mean bias) + Wasserstein label
    order = sorted(per, key=lambda m: per[m]["mean_bias"])
    fig, ax = plt.subplots(figsize=(7.6, 4.6))
    biases = [per[m]["mean_bias"] for m in order]
    cols = [CRIT if b >= 0.5 else (WARN if b >= 0.2 else (TEAL if b >= -0.2 else VIOLET)) for b in biases]
    ax.barh([short(m) for m in order], biases, color=cols)
    for i, m in enumerate(order):
        ax.text(biases[i] + (0.02 if biases[i] >= 0 else -0.02), i, f"W={per[m]['wasserstein']:.2f}",
                va="center", ha="left" if biases[i] >= 0 else "right", fontsize=8, color=MUTED)
    ax.axvline(0, color=INK, lw=1)
    ax.set_xlabel("mean bias  (judge mean - human mean; >0 = lenient)")
    ax.set_title("Per-judge leniency vs the human scores")
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
    ax.set_title("Do judges rank-agree with humans even while the scale shifts?")
    ax.grid(axis="y", visible=False); save(fig, "fig_pw_rankcorr.png"); plt.close(fig)

    # Fig E: reliability (valid-response-rate) -- the first gate
    rel_order = sorted(reliability, key=lambda k: reliability[k]["valid_response_rate"])
    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    rr = [reliability[k]["valid_response_rate"] * 100 for k in rel_order]
    cols = [CRIT if v < 50 else (WARN if v < 90 else TEAL) for v in rr]
    ax.barh(rel_order, rr, color=cols)
    for i, k in enumerate(rel_order):
        ax.text(rr[i] + 0.6, i, f"{rr[i]:.0f}%", va="center", fontsize=8, color=MUTED)
    ax.axvline(MIN_VALID_RATE * 100, color=INK, ls="--", lw=1, label=f"reliability gate {int(MIN_VALID_RATE*100)}%")
    ax.set_xlim(0, 108); ax.set_xlabel("valid structured-score rate (%)")
    ax.set_title("Can each model even be a judge? Valid-response rate")
    ax.legend(frameon=False, loc="lower right"); ax.grid(axis="y", visible=False)
    save(fig, "fig_pw_reliability.png"); plt.close(fig)

    print(f"pooled judge mean {report['pooled_judge_mean']} vs human {report['human_mean']} "
          f"(bias {pooled_bias:+.2f}, KS p={ks_all[1]:.2e})")
    if excluded:
        print("EXCLUDED (valid-rate <{:.0%}):".format(MIN_VALID_RATE),
              {e: reliability[e]["valid_response_rate"] for e in excluded})
    if per:
        print("per-judge mean bias",
              [round(min(v['mean_bias'] for v in per.values()), 2), round(max(v['mean_bias'] for v in per.values()), 2)],
              "| Spearman-r",
              [round(min(v['spearman_r'] for v in per.values()), 2), round(max(v['spearman_r'] for v in per.values()), 2)])
    print("wrote report.json, explorer_pointwise.json, 5 figures")


if __name__ == "__main__":
    main()
