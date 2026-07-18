# Assay

**The noise floor for LLM evals.** Every eval delta has a detection limit. Measure it before you ship it.

> The name: an **assay** determines what a material is actually made of, and every assay
> has a *limit of detection* below which signal cannot be told from a blank. That detection
> limit is the noise floor, and it is the first number Assay computes.

Assay is a statistics and audit layer for the eval harnesses you already run. It does not
ship runner number thirteen: it ingests the per-sample logs that lm-evaluation-harness,
Inspect AI, and HELM already emit and turns bare point estimates into decision-grade
measurements: clustered error bars, cluster-aware paired tests, a pre-flight
minimum-detectable-effect gate, and a cross-harness reconciler that pins a score gap on
the exact rule that caused it.

Every number Assay reports carries one of four provenance tags, enforced by a test:
`deterministic` · `statistically estimated` · `trained-model` · `LLM-judged`.

**[Live site (interactive)](https://aravinds-kannappan.github.io/Assay/)** ·
**[Walkthrough notebook](notebooks/assay_walkthrough.ipynb)** ·
**[Reproduced figures & outputs](results/)**

---

## Why

Most eval deltas are inside their own noise floor, and almost no eval tool reports
uncertainty. Three documented, measured facts this project is built around (each one Assay
re-derives in-repo rather than quoting):

- **Same generations, two parsers.** Identical frozen GSM8K outputs score ~62.8% under
  lm-eval `strict-match` and ~70.7% under `flexible-extract`. The model never changed; the
  regex did, and it can swap model order.
- **One benchmark, three harnesses.** A single 65B model on MMLU has scored `0.488 / 0.637 /
  0.636` across three published implementations that differ only in the answer-scoring rule.
- **The gold labels are wrong.** MMLU-Redux 2.0 finds a 6.49% error rate (57% in Virology);
  GSM8K-Platinum removed 110 of 1,319 items and relabeled 10. Corrected sets change who wins.

Numbers like these are anchors from the literature, treated here as hypotheses to
re-measure with confidence intervals. A failed replication is published as a finding.

---

## Status (v0.1)

This is an early, honest cut. What runs today, exercised by the test suite and on real
`--log_samples` files:

| Module | What it does | Status |
| --- | --- | --- |
| `assay.ingest` | lm-eval samples adapter into a unified per-sample schema | working |
| `assay.stats` | CLT SE, CR0/CR1/CR2 clustered SE, cluster bootstrap, exact + cluster-aware paired tests, MDE, Holm | working |
| `assay.reconcile` | GSM8K strict-vs-flexible reconciler with per-flip attribution | working |
| `assay.check` | tagged report: accuracy, clustered error bar, SE inflation, MDE | working |
| `assay.gate` (GitHub Action) | paired significance verdict on a PR: improve / regress / underpowered | working |
| `assay.irt` | 2PL item response model, Fisher-information fast subsets, ability estimation | working |
| `assay.judge` | LLM-judge calling (any OpenAI-compatible backend) + validation: kappa w/ clustered CI, position bias, verbosity | working |
| `assay.provenance` | four-tag system + `assert_all_tagged` (CI-enforced) | working |
| Inspect AI / HELM adapters | same schema, other harnesses | roadmap |
| benchmark linter | see the [roadmap](https://aravinds-kannappan.github.io/Assay/#roadmap) | roadmap |

The full design (13 modules, real datasets, two trained models with pre-registered kill
criteria, a 10-week roadmap) is on the **[project site](https://aravinds-kannappan.github.io/Assay/)**.

---

## Install

```bash
git clone https://github.com/aravinds-kannappan/Assay
cd Assay
python -m pip install -e .          # core: numpy + scipy only
python -m pip install -e ".[dev]"   # + pytest, pyarrow
python examples/make_fixtures.py    # regenerate the illustrative fixtures
```

## Quickstart

**1. Attribute a score gap to the code that caused it** (deterministic, no GPU):

```console
$ assay reconcile gsm8k examples/gsm8k_frozen.jsonl
  frozen generations : 24  (the model never re-ran)
  strict-match       :  54.17%   [deterministic]
  flexible-extract   :  87.50%   [deterministic]
  delta              : +33.33 pts  attributed to the extraction rule
  flexible recovered : 10  (strict missed the '####' delimiter)
  flexible fooled    : 2  (grabbed a trailing distractor)
  paired McNemar p   : 0.03857  [statistically estimated]
  verdict            : the harness moved the number, not the model
```

**2. Put an honest error bar on an eval** (clustered, because MMLU items share a subject):

```console
$ assay check examples/sample_lm_eval.jsonl --cluster-field subject
n = 48 items
accuracy = 0.5625  [deterministic]
clustered SE (CR2, 6 clusters) = 0.1790  [statistically estimated]
  95% CI = [0.2117, 0.9133]
  SE inflation vs naive = 2.47x
  ! only 6 clusters (<30): CR2 is shaky here; bootstrap SE cross-check = 0.1641
minimum detectable effect @ n=48: 20.06 pts  (alpha=0.05, power=0.8)
```

**3. Ask what an eval can even see, before spending tokens:**

```console
$ assay power --n 200 --p 0.7 --claim 0.021
  minimum detectable effect : 9.08 pts  [statistically estimated]
  claimed effect            : 2.10 pts  -> UNDERPOWERED
  items needed for claim    : ~3738  (unpaired; pairing cuts this substantially)
```

**4. Gate a PR on significance** (the underpowered-checkpoint demo):

```console
$ assay gate examples/gate_baseline.jsonl examples/gate_candidate.jsonl --cluster-field task
  baseline / candidate : 75.50%  ->  77.50%
  delta                : +2.00 pts
  MDE @ n=200          : 5.60 pts   [statistically estimated]
  paired test          : clustered-paired-z, p = 0.102
  VERDICT              : UNDERPOWERED: DELTA BELOW THE NOISE FLOOR
  items to resolve it  : ~1,570
```

Drop it into CI with the bundled composite action (posts the verdict as a PR comment):

```yaml
- uses: aravinds-kannappan/Assay/.github/actions/assay-gate@main
  with:
    baseline: runs/baseline.jsonl
    candidate: runs/candidate.jsonl
    cluster-field: subject
    fail-on-regression: "true"
```

**5. Fit a 2PL item response model** (real gradient descent, numpy/scipy only):

```console
$ assay irt fit examples/irt_outcomes.jsonl --subset 8
  models x items : 60 x 120
  converged      : True   log-likelihood -3736.4   [trained-model]
  ability theta  : mean +0.000, sd 0.684
  fast subset (8 items, most Fisher information): [92, 24, 87, 112, 54, 93, 111, 113]
```

Add `--json` to any command for the tagged, machine-readable report.

**6. Validate an LLM judge against human labels** (`assay.judge`, backend-agnostic):

```python
from assay.judge import judge_pairwise_debiased, validate_judge, OpenAICompatibleBackend
backend = OpenAICompatibleBackend()   # reads ASSAY_JUDGE_BASE_URL + ASSAY_JUDGE_API_KEY
# ...collect pref_ab / pref_ba per item across judges, then:
rep = validate_judge(human, pref_ab, pref_ba, clusters=subjects, len_a=la, len_b=lb)
# rep.cohens_kappa, rep.kappa_ci, rep.position_bias_rate, rep.length_correlation, rep.mde
```

A real pilot ran **10 live models across 7 providers** as judges on real Chatbot Arena
items in both A/B orderings. Headline finding: **9 of 10 judges were fully order-consistent;
Nemotron-Super flipped its verdict when A/B order swapped on 2 of 3 items (a clear
position-bias outlier)**. At N=3 the judge-ranking kappa CI is enormous, which is the point:
the module reports the item budget you need. Details, figures, and reproduction in
[`results/judge/`](results/judge/).

---

## The statistics, and why each piece is load-bearing

- **CR2 clustered SEs** (Bell-McCaffrey). Naive SEs understate uncertainty when items share
  a source (DROP passages, MMLU subjects, SWE-bench repos), which flips verdicts. CR2 reduces
  the small-cluster bias that CR0 suffers exactly in the few-cluster regime where eval data
  lives. A pairs-cluster bootstrap is the cross-check when clusters are few. *(For the
  intercept-only mean, CR2 has the closed form `SE = sqrt(sum_g R_g^2 / (1 - n_g/n)) / n`, and
  reduces exactly to the naive SE when every item is its own cluster: a property the test
  suite checks.)*
- **Cluster-aware paired inference.** Pairing is what makes small deltas testable at a
  fraction of the item budget; exact McNemar is used only when there is no cluster structure.
- **Power / MDE** (Miller, arXiv:2411.00640, Eq 9). The core promise: tell the user what the
  eval cannot resolve, up front.
- **Holm / Benjamini-Hochberg.** Because selecting a showcase result from many slices or
  leaderboard pairs without multiplicity control is the forking-paths error the tool polices.

---

## Real data (roadmap audits)

Assay's audits use real, public data only. Exact paths are pinned on the
[project site](https://aravinds-kannappan.github.io/Assay/#methods); highlights:

- `open-llm-leaderboard-old/details_*` and `open-llm-leaderboard/*-details`: per-sample
  outcomes for IRT (~34M real binary outcomes, split by base-model family).
- `edinburgh-dawg/mmlu-redux-2.0`, `madrylab/gsm8k-platinum` vs `openai/gsm8k`: relabeled
  gold for the benchmark linter and the ranking-flip engine.
- `evalplus/humanevalplus`, `evalplus/mbppplus`, `princeton-nlp/SWE-bench_Verified` (+ OpenAI
  annotations): weak-test and underspecification audits.
- `lmarena-ai/arena-human-preference-55k`, `allenai/reward-bench`: judge validation.
- HELM public bucket: the golden-test substrate (reproduce Miller Table 4 SE inflation).

The files in `examples/` are **synthetic illustrative fixtures** that use the real on-disk
*schema* so the code path is exercised offline and the tests have ground truth. They are not
real model outputs and are never reported as findings. See
[`examples/make_fixtures.py`](examples/make_fixtures.py).

---

## Development

```bash
python -m pytest -q                     # 47 tests: stats, reconciler, gate, IRT recovery, ingest, provenance
pip install -e ".[notebook]"            # matplotlib + jupyter
jupyter nbconvert --to notebook --execute notebooks/assay_walkthrough.ipynb   # regenerate results/ + figures
```

Run the notebook to reproduce every figure on the site from the shipped fixtures; outputs
land in [`results/`](results/) and are mirrored into `docs/figures/`. See
[docs/survey.md](docs/survey.md) for the (dated, to-be-verified) competitive survey of what
statistical machinery existing eval tools ship.

## How this was designed

The design was produced by a multi-agent workflow: five domain researchers (benchmark bugs,
eval statistics, real datasets, tooling gaps, trainable components), three competing project
concepts scored by an independent three-lens judge panel, and one synthesis that absorbed the
strongest ideas from the runners-up.

## License

MIT. See [LICENSE](LICENSE).
