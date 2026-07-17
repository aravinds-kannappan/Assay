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
