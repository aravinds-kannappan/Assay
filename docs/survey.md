# Competitive survey: what statistics do eval tools ship?

**Compiled 2026-07-16. This table is a starting point to be re-verified against each
tool's current release before it is cited.** A project that preaches skepticism must make
its own competitive claims auditable, so this file is dated, versioned with the repo, and
marked where a cell needs live confirmation.

The claim Assay makes ("almost no eval tool reports uncertainty as a first-class output")
should be checked, not trusted. Columns:

- **Clustered SE**: reports standard errors that account for items sharing a source.
- **Paired test**: a first-class paired significance test between two models on shared items.
- **Power / MDE**: tells you what effect size the eval can resolve before you run it.
- **Label-error audit**: flags likely-wrong gold labels or weak tests.
- **Replay pinning**: captures prompt hash + dataset revision so a number is reproducible.

| Tool | Point est. | Clustered SE | Paired test | Power / MDE | Label-error audit | Replay pinning |
| --- | --- | --- | --- | --- | --- | --- |
| lm-evaluation-harness | yes | naive stderr only (verify) | no (verify) | no | no | partial (verify) |
| Inspect AI | yes | naive stderr (verify) | no (verify) | no | no | yes (`.eval` logs) |
| HELM | yes | no (verify) | no (verify) | no | no | yes (predictions) |
| OpenAI simple-evals | yes | no | no | no | no | partial |
| EvalPlus | yes (pass@k) | n/a | no | no | weak-test focus | n/a |
| promptfoo | yes | no | no | no | no | partial |
| DeepEval | yes | no | no | no | no | no |
| Braintrust / Weave / Phoenix | yes | no (verify) | no (verify) | no | no | yes (tracing) |
| **Assay (this project)** | yes | **CR0/CR1/CR2 + bootstrap** | **exact + cluster-aware** | **yes (Miller Eq 9)** | roadmap (linter) | **yes (prompt SHA256 + revision)** |

Notes and honesty caveats:

- Cells marked `(verify)` are from model knowledge as of the compile date and must be
  confirmed against the tool's current docs/source before this table is used as marketing.
- "naive stderr only" means an i.i.d. standard error is available but not a cluster-robust
  one; several harnesses do surface a bare stderr, which is better than nothing and should
  be credited as such.
- Assay is deliberately a *layer*, not a runner: the comparison is about statistical
  machinery, not about who executes the model.

---

## Recent literature (pulled live via Serper Scholar + You.com)

The methods Assay implements are the ones the current literature converges on. Raw search
output is saved in [`results/survey/`](../results/survey/). Selected sources:

**Eval statistics.**
- Miller, *Adding error bars to evals* (arXiv:2411.00640): CLT and clustered standard
  errors, paired comparisons, power. The paper Assay's golden tests reproduce.
- *Position: Don't Use the CLT in LLM Evals With Fewer Than a Few Hundred Datapoints*
  (arXiv:2503.01747): motivates the small-cluster / bootstrap path.
- *Handling Missing Responses under Cluster Dependence* (NeurIPS 2025): cluster structure
  in eval estimation, the regime Assay's CR2 targets.

**LLM-as-a-judge bias.**
- *Judging the judges: A systematic study of position bias in LLM-as-a-judge*
  (IJCNLP 2025, 288 citations): the exact position-bias effect `assay.judge` measures via
  swap-and-average, and which the pilot found in Nemotron-Super.
- *Are We on the Right Way to Assessing LLM-as-a-Judge?* (arXiv:2512.16041) and
  *Judging the judges: alignment and vulnerabilities* (GEM 2025, 269 citations): verbosity
  bias and human-agreement, mapped to `validate_judge`'s length correlation + Cohen's kappa.
- A You.com synthesis of 2024-2026 practice (saved in `results/survey/you_research.json`)
  independently prescribes the same toolkit: clustered SEs, order swap-and-average,
  verbosity control, kappa calibration, and diverse-provider judge panels.

**IRT / efficient evaluation.**
- *tinyBenchmarks* (arXiv:2402.14992, 144 citations) and *Lost in benchmarks? Rethinking
  LLM benchmarking with IRT* (AAAI 2026): the 2PL fast-subset approach `assay.irt` implements.

**Contamination** (roadmap for `assay.audit`): *LiveCodeBench* (ICLR 2025) and the
static-to-dynamic contamination survey (EMNLP 2025).
