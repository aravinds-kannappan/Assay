# LLM-judge panel pilot

A real run of `assay.judge`: **10 live models across 7 providers** judging **real
Chatbot Arena items** against the human preference, in both A/B orderings, with the
statistics computed by `assay.stats`.

## What this is (and is not)

This is an **N=3 pilot** on three real Arena items (`it0`, `it2`, `it5`). Its job is to
exercise the full pipeline end to end with real models and real human labels, and to
show the statistics working. It is **deliberately small**: at N=3 the judge-ranking
statistics are radically underpowered (the pooled kappa CI is enormous), which is the
whole point. `assay.judge` reports the item budget you actually need; run it with your
own key to do the full study.

## The panel

`openai/gpt-oss-120b` (OpenAI), `nvidia/Nemotron-120B-A12B` and
`nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B` (NVIDIA), `zai-org/GLM-4.7`, `zai-org/GLM-5`,
`zai-org/GLM-5.2` (Z.ai), `moonshotai/Kimi-K2.5`, `moonshotai/Kimi-K2.7-Code` (Moonshot),
`deepseek-ai/DeepSeek-V4-Pro` (DeepSeek), `thinkingmachines/inkling` (Thinking Machines).

## Findings (see `judge_report.json`)

- **Position bias:** 9 of 10 judges were 100% order-consistent on the items they
  completed; **Nemotron-Super flipped its verdict when A/B order swapped on 2 of 3 items
  (33% consistent)**, a clear outlier (`figJ1_position_bias.png`).
- **Structured-output reliability:** 3 judges emitted non-standard JSON keys
  (`better` / `choice` / `better_response`) despite a `json_schema`, and 2 reasoning
  judges returned `null` on the hardest item under a 600-token cap (fixed by raising
  `max_tokens` to 2048). A real operational finding for anyone wiring these as judges.
- **Agreement:** pooled human agreement 77%, Cohen's kappa +0.55 with an item-clustered
  95% CI of about [0.00, 0.61]: the judges mostly agreed on the two clear items and split
  on a letter-uniqueness puzzle (`figJ2_judge_agreement.png`).

## Reproduce

The **analysis** is fully reproducible offline from the committed verdicts:

```bash
python scripts/analyze_judge.py    # rebuilds judge_report.json + figJ1/figJ2
```

The **raw verdict collection** called the 10 models through an OpenAI-compatible endpoint
using `assay.judge` (temperature 0, seed 42, both orderings, a compact `preferred`/
`confidence` schema). That step needs an API key and is not rerun here. To run the full
study yourself:

```python
from assay.judge import judge_pairwise_debiased, validate_judge, OpenAICompatibleBackend
backend = OpenAICompatibleBackend()   # ASSAY_JUDGE_BASE_URL + ASSAY_JUDGE_API_KEY
# ... loop items x models, then validate_judge(human, pref_ab, pref_ba, clusters=...)
```

## Files

| File | What |
| --- | --- |
| `verdicts.jsonl` | 30 rows (3 items x 10 models): item, human winner, model, `pref_ab`, `pref_ba` (original A/B frame) |
| `judge_report.json` | per-model + pooled statistics and headline findings |
| `it0/it2/it5_verdicts.json` | per-item raw verdicts |
| `run_items.json` | the Arena items used (prompt, both responses, human winner) |

The Arena items are real; nothing here is synthetic. The verdicts are `[LLM-judged]`; the
statistics on top are `[statistically estimated]`.
