"""LLM-as-judge calling + validation.

Two halves, deliberately separable:

1. **Calling** an LLM judge (pairwise or pointwise) through any OpenAI-compatible
   endpoint. The API call is behind a ``JudgeBackend`` so the package never hard-codes
   a provider: plug in Baseten, OpenAI, a local vLLM, or a fake for tests.

2. **Validating** a judge against human labels with real statistics: chance-corrected
   agreement (Cohen's kappa) with a cluster-aware bootstrap CI, a position-bias rate
   with a paired test, a length (verbosity) correlation, and the minimum detectable
   effect at the current item count. These functions are pure: no API, fully testable.

Provenance: a judge's `preferred`/`score` is [LLM-judged]. Every statistic computed on
top of judge outputs is [statistically estimated] and names the [LLM-judged] input.
"""
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Literal, Optional, Sequence

from . import stats

Choice = Literal["A", "B"]


# ---- data structures ------------------------------------------------------

@dataclass
class JudgeVerdict:
    """A single pairwise judgment. Tag: [LLM-judged]."""
    preferred: Choice
    confidence: int          # 1-5
    reasoning: str
    model: str
    item_id: str
    order: Literal["AB", "BA"]   # which response was shown first
    seed: Optional[int] = None
    raw: Optional[dict] = None    # raw provider response, if kept


@dataclass
class PointwiseScore:
    """A single pointwise score. Tag: [LLM-judged]."""
    score: int               # 1-5
    reasoning: str
    model: str
    item_id: str
    raw: Optional[dict] = None


@dataclass
class DebiasedVerdict:
    """A pairwise verdict judged in both orderings to check position bias."""
    verdict_ab: JudgeVerdict
    verdict_ba: JudgeVerdict
    consistent: bool                       # did both orderings agree in the A/B frame?
    final_preferred: Literal["A", "B", "tie"]


@dataclass
class JudgeValidationReport:
    """Full judge-vs-human validation. Numbers are [statistically estimated]
    over [LLM-judged] inputs unless noted."""
    model: str
    n_items: int
    agreement_rate: float                  # [deterministic] fraction judge == human
    cohens_kappa: float                    # [statistically estimated]
    kappa_ci: tuple[float, float]
    kappa_se: float
    position_bias_rate: Optional[float]    # fraction where AB and BA disagreed
    position_bias_p: Optional[float]       # paired (McNemar) test on AB vs BA
    length_correlation: Optional[float]    # Spearman rho: length diff vs preference
    length_correlation_p: Optional[float]
    mde: float                             # smallest agreement gap resolvable at n
    items_needed: Optional[int]            # n to resolve the observed agreement vs chance
    n_clusters: Optional[int]
    provenance: str = "statistically estimated over LLM-judged inputs"


# ---- prompt + schema builders --------------------------------------------

PAIRWISE_SYSTEM = (
    "You are an impartial judge evaluating two AI assistant responses to a user prompt. "
    "Judge on helpfulness, accuracy, and relevance. Do not let the order of the responses, "
    "their length, or their style bias you. Output valid JSON only."
)

POINTWISE_SYSTEM = (
    "Score the response on a 1-5 scale. 1=poor, 2=below average, 3=adequate, 4=good, "
    "5=excellent. Judge accuracy, helpfulness, and completeness. Output valid JSON only."
)


def build_pairwise_messages(prompt: str, response_a: str, response_b: str) -> list[dict]:
    user = (f"User prompt:\n{prompt}\n\nResponse A:\n{response_a}\n\nResponse B:\n{response_b}\n\n"
            "Which response is better, A or B? State your preference and confidence.")
    return [{"role": "system", "content": PAIRWISE_SYSTEM}, {"role": "user", "content": user}]


def build_pointwise_messages(prompt: str, response: str, rubric: str = "") -> list[dict]:
    extra = f"\n\nRubric:\n{rubric}" if rubric else ""
    user = f"User prompt:\n{prompt}\n\nResponse:\n{response}{extra}\n\nScore this response 1-5."
    return [{"role": "system", "content": POINTWISE_SYSTEM}, {"role": "user", "content": user}]


def pairwise_schema(with_reasoning: bool = True) -> dict:
    props = {"preferred": {"type": "string", "enum": ["A", "B"]},
             "confidence": {"type": "integer", "minimum": 1, "maximum": 5}}
    required = ["preferred", "confidence"]
    if with_reasoning:
        props["reasoning"] = {"type": "string"}
        required.append("reasoning")
    return {"type": "json_schema", "json_schema": {"name": "pairwise_verdict",
            "schema": {"type": "object", "properties": props, "required": required}}}


def pointwise_schema() -> dict:
    return {"type": "json_schema", "json_schema": {"name": "pointwise_score",
            "schema": {"type": "object", "properties": {
                "score": {"type": "integer", "minimum": 1, "maximum": 5},
                "reasoning": {"type": "string"}},
                "required": ["score", "reasoning"]}}}


# ---- backends -------------------------------------------------------------

# A backend takes an OpenAI-style request body and returns the response dict.
JudgeBackend = Callable[[dict], dict]


class OpenAICompatibleBackend:
    """Minimal stdlib backend for any OpenAI-compatible /v1/chat/completions endpoint.

    Reads base_url and api_key from args or the env vars ASSAY_JUDGE_BASE_URL /
    ASSAY_JUDGE_API_KEY. No third-party dependency (uses urllib).
    """

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, timeout: int = 120):
        self.base_url = (base_url or os.environ.get("ASSAY_JUDGE_BASE_URL", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("ASSAY_JUDGE_API_KEY", "")
        self.timeout = timeout

    def __call__(self, body: dict) -> dict:
        if not self.base_url:
            raise RuntimeError("no base_url set (pass base_url= or set ASSAY_JUDGE_BASE_URL)")
        req = urllib.request.Request(
            self.base_url + "/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))


def parse_content(response: dict) -> dict:
    """Extract and JSON-parse the assistant message content from an OpenAI response."""
    content = response["choices"][0]["message"]["content"]
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content[content.find("{"):content.rfind("}") + 1]
    return json.loads(content)


# ---- judge calls ----------------------------------------------------------

def judge_pairwise(
    prompt: str, response_a: str, response_b: str, *,
    model: str, backend: JudgeBackend,
    item_id: str = "", order: Literal["AB", "BA"] = "AB",
    temperature: float = 0.0, max_tokens: int = 800, seed: int = 42,
    reasoning_effort: str = "low", with_reasoning: bool = True,
) -> JudgeVerdict:
    """Call an LLM judge for a pairwise preference. Tag: [LLM-judged]."""
    if order == "BA":
        response_a, response_b = response_b, response_a
    body = {
        "model": model, "messages": build_pairwise_messages(prompt, response_a, response_b),
        "temperature": temperature, "max_tokens": max_tokens, "seed": seed,
        "reasoning_effort": reasoning_effort, "response_format": pairwise_schema(with_reasoning),
    }
    resp = backend(body)
    v = parse_content(resp)
    raw_choice = v["preferred"]
    # Fold the BA ordering back into the original A/B frame so verdicts are comparable.
    preferred = raw_choice if order == "AB" else ("A" if raw_choice == "B" else "B")
    return JudgeVerdict(preferred=preferred, confidence=int(v.get("confidence", 3)),
                        reasoning=v.get("reasoning", ""), model=model, item_id=item_id,
                        order=order, seed=seed)


def judge_pairwise_debiased(
    prompt: str, response_a: str, response_b: str, *,
    model: str, backend: JudgeBackend, item_id: str = "", **kw,
) -> DebiasedVerdict:
    """Judge both orderings and report whether the verdict is order-consistent."""
    ab = judge_pairwise(prompt, response_a, response_b, model=model, backend=backend,
                        item_id=item_id, order="AB", **kw)
    ba = judge_pairwise(prompt, response_a, response_b, model=model, backend=backend,
                        item_id=item_id, order="BA", **kw)
    consistent = ab.preferred == ba.preferred
    final = ab.preferred if consistent else "tie"
    return DebiasedVerdict(verdict_ab=ab, verdict_ba=ba, consistent=consistent, final_preferred=final)


def judge_pointwise(
    prompt: str, response: str, *, rubric: str = "", model: str, backend: JudgeBackend,
    item_id: str = "", temperature: float = 0.0, max_tokens: int = 400, seed: int = 42,
    reasoning_effort: str = "low",
) -> PointwiseScore:
    """Call an LLM judge for a 1-5 pointwise score. Tag: [LLM-judged]."""
    body = {"model": model, "messages": build_pointwise_messages(prompt, response, rubric),
            "temperature": temperature, "max_tokens": max_tokens, "seed": seed,
            "reasoning_effort": reasoning_effort, "response_format": pointwise_schema()}
    v = parse_content(backend(body))
    return PointwiseScore(score=int(v["score"]), reasoning=v.get("reasoning", ""),
                          model=model, item_id=item_id)


# ---- validation (pure stats, no API) --------------------------------------

def _debias(pref_ab: Sequence[Choice], pref_ba: Optional[Sequence[Choice]]):
    if pref_ba is None:
        return list(pref_ab), None
    final, swaps = [], []
    for x, y in zip(pref_ab, pref_ba):
        swaps.append(x != y)
        final.append(x if x == y else "tie")
    return final, swaps


def validate_judge(
    human: Sequence[Choice],
    pref_ab: Sequence[Choice],
    pref_ba: Optional[Sequence[Choice]] = None,
    *,
    model: str = "",
    clusters: Optional[Sequence] = None,
    len_a: Optional[Sequence[float]] = None,
    len_b: Optional[Sequence[float]] = None,
    alpha: float = 0.05,
    power: float = 0.8,
) -> JudgeValidationReport:
    """Validate one judge against human labels.

    ``pref_ab`` / ``pref_ba`` are the judge's preferences (in the original A/B frame)
    for the two orderings; pass ``pref_ba`` to measure position bias. All lists are
    aligned by item.
    """
    human = list(human)
    n = len(human)
    if len(pref_ab) != n:
        raise ValueError("human and pref_ab must be equal length")
    final, swaps = _debias(pref_ab, pref_ba)

    # Agreement + kappa on decisive items (drop order-inconsistent 'tie's).
    keep = [i for i, f in enumerate(final) if f in ("A", "B")]
    jh_judge = [final[i] for i in keep]
    jh_human = [human[i] for i in keep]
    agree = stats.agreement_rate(jh_judge, jh_human) if keep else float("nan")
    kappa = stats.cohens_kappa(jh_judge, jh_human) if keep else float("nan")
    cl = [clusters[i] for i in keep] if clusters is not None else None
    lo, hi, se = stats.kappa_bootstrap_ci(jh_judge, jh_human, clusters=cl) if len(keep) > 1 else (float("nan"),) * 3

    # Position bias: how often the two orderings disagreed, and is it systematic?
    pos_rate = pos_p = None
    if swaps is not None:
        pos_rate = sum(swaps) / n
        # McNemar on "judge said A" under AB vs BA orderings.
        ab01 = [1.0 if x == "A" else 0.0 for x in pref_ab]
        ba01 = [1.0 if x == "A" else 0.0 for x in pref_ba]
        pos_p = stats.paired_mcnemar(ab01, ba01).p_value

    # Length / verbosity bias: does the judge prefer the longer response?
    lc = lc_p = None
    if len_a is not None and len_b is not None:
        diff = [float(len_a[i]) - float(len_b[i]) for i in keep]
        signed = [1.0 if final[i] == "A" else -1.0 for i in keep]
        if len(set(diff)) > 1 and len(set(signed)) > 1:
            lc, lc_p = stats.spearman(diff, signed)

    # Power: can this many items even separate the judge from a coin flip?
    p_hat = agree if agree == agree else 0.5
    mde = stats.mde_absolute(max(len(keep), 1), p_hat, alpha=alpha, power=power)
    items_needed = None
    eff = abs(p_hat - 0.5)
    if eff > 0:
        import math
        items_needed = stats.required_n(eff, math.sqrt(max(p_hat * (1 - p_hat), 1e-12)), alpha, power)

    return JudgeValidationReport(
        model=model, n_items=n, agreement_rate=agree, cohens_kappa=kappa,
        kappa_ci=(lo, hi), kappa_se=se, position_bias_rate=pos_rate, position_bias_p=pos_p,
        length_correlation=lc, length_correlation_p=lc_p, mde=mde, items_needed=items_needed,
        n_clusters=(len(set(cl)) if cl is not None else None),
    )


def reconcile_judges(
    item_ids: Sequence[str],
    judge_a: Sequence[Choice],
    judge_b: Sequence[Choice],
    name_a: str = "judge_a",
    name_b: str = "judge_b",
) -> dict:
    """Per-item attribution of where two judges disagree, plus a McNemar test.

    Reuses the reconciler idea: agreement is [deterministic], the McNemar test that
    asks whether the disagreement is systematic is [statistically estimated].
    """
    ia, ib = list(judge_a), list(judge_b)
    ids = list(item_ids)
    if not (len(ia) == len(ib) == len(ids)):
        raise ValueError("inputs must be equal length")
    disagreements = [{"item_id": ids[i], name_a: ia[i], name_b: ib[i]}
                     for i in range(len(ids)) if ia[i] != ib[i]]
    a01 = [1.0 if x == "A" else 0.0 for x in ia]
    b01 = [1.0 if x == "A" else 0.0 for x in ib]
    mc = stats.paired_mcnemar(a01, b01)
    return {
        "agreement_rate": stats.agreement_rate(ia, ib),   # [deterministic]
        "n_disagreements": len(disagreements),
        "mcnemar_p": mc.p_value,                           # [statistically estimated]
        "disagreements": disagreements,
    }
