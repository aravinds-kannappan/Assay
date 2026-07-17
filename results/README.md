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

The figures are mirrored into `docs/figures/` so the project site shows exactly these outputs.
All numbers come from the synthetic illustrative fixtures in `examples/` and demonstrate the
method, not a finding.
