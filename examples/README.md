# Example fixtures

**These are synthetic illustrative fixtures, not real data.**

They use the real on-disk *schema* of the inputs Assay consumes, so the adapters
and the reconciler run through the exact code path they would on real data, and
the unit tests have deterministic ground truth. They contain no real model
outputs and no real benchmark content.

| File | Schema mirrored | Purpose |
| --- | --- | --- |
| `gsm8k_frozen.jsonl` | frozen GSM8K generations (`gold`, `completion`) | show the strict-vs-flexible extraction gap; golden values for `test_reconcile.py` |
| `sample_lm_eval.jsonl` | lm-eval `--log_samples` output with a `subject` cluster | show clustered-SE inflation and the small-cluster path; input for `test_ingest.py` |

Regenerate them with:

```bash
python examples/make_fixtures.py
```

The illustrative GSM8K gap here (~33 pts) is deliberately exaggerated to make the
mechanism obvious. The **real** reproduction runs on actual model generations and
recovers the documented ~8-point strict-vs-flexible gap. Assay's real audits use
public datasets only (Open LLM Leaderboard details, GSM8K-Platinum, MMLU-Redux,
HELM logs); see [`../docs/plan.html`](../docs/plan.html). Nothing in this folder
should ever be reported as a finding.
