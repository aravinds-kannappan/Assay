"""Analyze the LLM-judge study from whatever verdict chunks exist.

Reads results/judge_full/chunks/chunk_*.jsonl, validates every judge against the
human labels with assay.stats, aggregates the panel, builds the judge-vs-judge
agreement matrix, and writes:
  results/judge/report.json          per-model + panel + matrix
  results/judge/explorer_data.json   items + per-judge verdicts & reasoning (site)
  results/figures/fig_judge_*.png     (mirrored into docs/figures/)

Data-driven: run it again after more chunks land and everything regenerates.
Usage: python scripts/analyze_judge.py
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

from assay import judge as J

ROOT = Path(__file__).resolve().parent.parent
CHUNKS = ROOT / "results" / "judge_full" / "chunks"
OUTJ = ROOT / "results" / "judge"; OUTJ.mkdir(parents=True, exist_ok=True)
FIGS = ROOT / "results" / "figures"; FIGS.mkdir(parents=True, exist_ok=True)
DOCS_FIGS = ROOT / "docs" / "figures"; DOCS_FIGS.mkdir(parents=True, exist_ok=True)
DOCS = ROOT / "docs"
ITEMS = json.load(open(ROOT / "results" / "judge_full" / "items.json"))
ITEM_BY_ID = {it["item_id"]: it for it in ITEMS}

PROVIDERS = {"openai": "OpenAI", "nvidia": "NVIDIA", "zai-org": "Z.ai", "moonshotai": "Moonshot",
             "deepseek-ai": "DeepSeek", "thinkingmachines": "Thinking Machines"}
def provider(m): return PROVIDERS.get(m.split("/")[0], m.split("/")[0])

INK, TEAL, MUTED, WARN, CRIT, GRID = "#10171C", "#0C8C7E", "#63727C", "#B26E12", "#C24248", "#D6DDD9"
plt.rcParams.update({"figure.facecolor": "white", "axes.facecolor": "white", "axes.edgecolor": MUTED,
    "axes.labelcolor": INK, "text.color": INK, "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.8, "font.size": 10.5, "axes.titlesize": 12, "axes.titleweight": "bold",
    "figure.dpi": 150, "savefig.bbox": "tight", "axes.spines.top": False, "axes.spines.right": False})


def short(m): return m.split("/")[-1]
def save(fig, name):
    for d in (FIGS, DOCS_FIGS): fig.savefig(d / name, dpi=150)


def load_rows():
    rows = []
    for f in sorted(glob.glob(str(CHUNKS / "chunk_*.jsonl"))):
        if f.endswith("chunk_test.jsonl"):  # the pipeline smoke-test artifact
            continue
        for l in open(f):
            l = l.strip()
            if not l:
                continue
            try:
                r = json.loads(l)
            except Exception:
                continue
            if r.get("item_id") in ITEM_BY_ID and "human" in r:  # well-formed study rows only
                rows.append(r)
    return rows


def final_pref(r):
    ab, ba = r.get("pref_ab"), r.get("pref_ba")
    if ab in ("A", "B") and ba in ("A", "B"):
        return ab if ab == ba else "tie"
    return ab if ab in ("A", "B") else (ba if ba in ("A", "B") else None)


def main():
    rows = load_rows()
    models = sorted({r["model"] for r in rows})
    item_ids = sorted({r["item_id"] for r in rows})
    by = {(r["item_id"], r["model"]): r for r in rows}
    n = len(item_ids)
    print(f"loaded {len(rows)} rows | {n} items | {len(models)} judges")

    per_model = {}
    finals = {m: {} for m in models}
    for m in models:
        H, AB, BA, LA, LB, kept = [], [], [], [], [], []
        for iid in item_ids:
            r = by.get((iid, m))
            finals[m][iid] = final_pref(r) if r else None
            if not r or r.get("pref_ab") not in ("A", "B") or r.get("pref_ba") not in ("A", "B"):
                continue
            H.append(r["human"]); AB.append(r["pref_ab"]); BA.append(r["pref_ba"])
            LA.append(r["len_a"]); LB.append(r["len_b"]); kept.append(iid)
        if len(kept) < 2:
            continue
        rep = J.validate_judge(H, AB, BA, model=m, len_a=LA, len_b=LB)
        per_model[m] = {
            "n": rep.n_items, "agreement": round(rep.agreement_rate, 3),
            "cohens_kappa": round(rep.cohens_kappa, 3),
            "kappa_ci": [round(rep.kappa_ci[0], 3), round(rep.kappa_ci[1], 3)],
            "position_bias_rate": round(rep.position_bias_rate, 3) if rep.position_bias_rate is not None else None,
            "position_bias_p": round(rep.position_bias_p, 4) if rep.position_bias_p is not None else None,
            "length_correlation": round(rep.length_correlation, 3) if rep.length_correlation is not None else None,
            "mde": round(rep.mde, 4), "items_needed": rep.items_needed,
        }

    # panel (ensemble)
    panel_by = {}; correct = decided = 0
    for iid in item_ids:
        fs = [finals[m].get(iid) for m in models]
        pv = J.panel_verdict(fs)
        human = ITEM_BY_ID[iid]["human_winner"]
        pv["item_id"] = iid; pv["human"] = human
        pv["panel_correct"] = (pv["panel_preferred"] == human) if pv["panel_preferred"] in ("A", "B") else None
        if pv["panel_correct"] is not None:
            decided += 1; correct += int(pv["panel_correct"])
        panel_by[iid] = pv
    panel_acc = correct / decided if decided else float("nan")

    # judge x judge agreement matrix
    matrix = {}
    for a in models:
        matrix[a] = {}
        for b in models:
            both = [(finals[a][i], finals[b][i]) for i in item_ids
                    if finals[a].get(i) in ("A", "B") and finals[b].get(i) in ("A", "B")]
            matrix[a][b] = round(sum(1 for x, y in both if x == y) / len(both), 3) if both else None

    best_single = max((v["agreement"] for v in per_model.values()), default=0)
    report = {"n_items": n, "n_judges": len(models),
              "provenance": "verdicts [LLM-judged]; agreement/kappa/bias [statistically estimated]",
              "per_model": per_model,
              "panel": {"accuracy_vs_human": round(panel_acc, 3), "n_decided": decided,
                        "best_single_agreement": round(best_single, 3)},
              "judge_agreement_matrix": matrix}
    json.dump(report, open(OUTJ / "report.json", "w"), indent=2)

    # explorer data (shape consumed by docs/index.html judge tab)
    explorer = []
    for iid in item_ids:
        it = ITEM_BY_ID[iid]
        pv = panel_by[iid]
        judges = []
        for m in models:
            r = by.get((iid, m))
            if not r: continue
            judges.append({"model": short(m), "provider": provider(m), "final": finals[m].get(iid),
                           "conf": r.get("conf_ab"), "reason": (r.get("reason_ab") or "")[:240]})
        explorer.append({"item_id": iid, "prompt": it["prompt"][:700],
                         "response_a": it["response_a"][:850], "response_b": it["response_b"][:850],
                         "model_a": it["model_a"], "model_b": it["model_b"], "human": it["human_winner"],
                         "panel": {"panel_preferred": pv["panel_preferred"], "votes_a": pv["votes_a"],
                                   "votes_b": pv["votes_b"], "n_abstain": pv["n_abstain"]},
                         "judges": judges})
    payload = {"n_items": n, "n_judges": len(models), "panel_accuracy": round(panel_acc, 3),
               "best_single": round(best_single, 3), "items": explorer}
    json.dump(payload, open(OUTJ / "explorer_data.json", "w"))
    json.dump(payload, open(DOCS / "judge_explorer.json", "w"))  # served by the site

    # figures
    order = sorted(per_model, key=lambda m: per_model[m]["cohens_kappa"])
    fig, ax = plt.subplots(figsize=(7.8, 4.7))
    for i, m in enumerate(order):
        k = per_model[m]["cohens_kappa"]; lo, hi = per_model[m]["kappa_ci"]
        ax.plot([lo, hi], [i, i], color=TEAL, lw=2.2); ax.plot(k, i, "o", color=INK, ms=6)
    ax.axvline(0, color=CRIT, ls="--", lw=1.2)
    ax.set_yticks(range(len(order))); ax.set_yticklabels([short(m) for m in order])
    ax.set_xlabel("Cohen's kappa vs human (95% bootstrap CI)")
    ax.set_title(f"Judge agreement with humans (N={n}); overlapping CIs = can't yet rank judges")
    ax.grid(axis="y", visible=False); save(fig, "fig_judge_kappa.png"); plt.close(fig)

    ob = sorted(per_model, key=lambda m: per_model[m]["position_bias_rate"] or 0)
    fig, ax = plt.subplots(figsize=(7.8, 4.4))
    vals = [(per_model[m]["position_bias_rate"] or 0) * 100 for m in ob]
    cols = [CRIT if v >= 30 else (WARN if v >= 15 else TEAL) for v in vals]
    ax.barh([short(m) for m in ob], vals, color=cols)
    for i, v in enumerate(vals): ax.text(v + 0.4, i, f"{v:.0f}%", va="center", fontsize=9, color=MUTED)
    ax.set_xlabel("position-bias rate (verdict flips when A/B order swaps)")
    ax.set_title(f"Position bias by judge (N={n}, both orderings)")
    ax.grid(axis="y", visible=False); save(fig, "fig_judge_position_bias.png"); plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.9, 6.1))
    Mx = np.array([[matrix[a][b] if matrix[a][b] is not None else np.nan for b in models] for a in models])
    im = ax.imshow(Mx, cmap="BuGn", vmin=0.4, vmax=1.0)
    ax.set_xticks(range(len(models))); ax.set_xticklabels([short(m) for m in models], rotation=90, fontsize=7)
    ax.set_yticks(range(len(models))); ax.set_yticklabels([short(m) for m in models], fontsize=7)
    for i in range(len(models)):
        for j in range(len(models)):
            if not np.isnan(Mx[i, j]): ax.text(j, i, f"{Mx[i,j]:.2f}", ha="center", va="center", fontsize=6,
                                                color="white" if Mx[i, j] > 0.82 else INK)
    ax.set_title(f"Judge-vs-judge agreement (N={n})")
    fig.colorbar(im, fraction=0.046, pad=0.04); save(fig, "fig_judge_heatmap.png"); plt.close(fig)

    print(f"panel accuracy vs human: {panel_acc*100:.0f}% over {decided} decided (best single judge {best_single*100:.0f}%)")
    ks = [v["cohens_kappa"] for v in per_model.values()]
    print(f"kappa range: {min(ks):.2f} to {max(ks):.2f}")
    print("wrote report.json, explorer_data.json, 3 figures")


if __name__ == "__main__":
    main()
