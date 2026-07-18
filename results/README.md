# results/

Reproducible outputs of [`notebooks/assay_walkthrough.ipynb`](../notebooks/assay_walkthrough.ipynb).
Re-running the notebook regenerates every file here (the one stochastic step, a bootstrap SE, is seeded).

| File | What |
| --- | --- |
| `figures/fig1_noise_floor_mde.png` | minimum detectable effect vs eval size (the noise floor) |
| `figures/fig2_error_bars.png` | naive vs CR2 vs bootstrap error bars on the same accuracy |
| `figures/fig3_reconciler.png` | strict-vs-flexible GSM8K waterfall with recovered/fooled |
| `figures/fig4_subject_clusters.png` | per-subject accuracy (why a subject is a cluster) |
| `figures/fig5_paired_required_n.png` | items required, paired vs unpaired |
| `figures/fig6_gate.png` | the gate: a +2 pt claim sitting inside the noise floor |
| `figures/fig7_irt_recovery.png` | 2PL parameter recovery, fit vs known truth |
| `figures/fig8_irt_icc.png` | item characteristic curves |
| `figures/fig9_ability_vs_accuracy.png` | IRT ability vs raw accuracy |
| `figures/fig10_fast_subset.png` | Fisher-information fast subsets vs random |
| `reconcile_gsm8k.json` | reconciler output + every attributed flip |
| `check_mmlu_fixture.json` | full tagged check report (accuracy, clustered SE, MDE) |
| `mde_table.csv` | MDE at each eval size for p = 0.5 / 0.7 / 0.9 |
| `summary.json` | consolidated headline numbers |

The figures above come from the synthetic illustrative fixtures in `examples/` and demonstrate
the method, not a finding. The subfolders below hold **real** API-backed outputs.

## Subfolders (real, API-backed output)

| Folder | What | Provenance |
| --- | --- | --- |
| `judge/` | 10-model x 7-provider judge pilot on real Chatbot Arena items: verdicts, report, figures | verdicts `[LLM-judged]`, stats `[statistically estimated]` |
| `real_data/` | key facts re-derived live from HuggingFace: MMLU-Redux 2.0 error rate = **6.49%** (Virology 57%), GSM8K to Platinum = **110 items removed** | `[deterministic]`, recomputed from HF datasets-server |
| `survey/` | live literature pull (Serper Scholar `serper_scholar.json`, You.com research `you_research.json`) backing `docs/survey.md` | external sources, dated |
| `tako/` | interactive chart card (embed/image/webpage URLs) for the judge order-consistency figure | Tako card over deterministic input |
| `scrape/` | ScrapeGraphAI markdown of the MMLU-Redux dataset page (real page content) | external source |

Figures are mirrored into `docs/figures/` so the site shows exactly these outputs.
