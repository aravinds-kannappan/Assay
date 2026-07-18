import json

import pytest

from assay import stats
from assay.judge import (
    DebiasedVerdict,
    judge_pairwise,
    judge_pairwise_debiased,
    parse_content,
    reconcile_judges,
    validate_judge,
)


# ---- statistics -----------------------------------------------------------

def test_cohens_kappa_perfect_and_chance():
    assert stats.cohens_kappa(["A", "B", "A", "B"], ["A", "B", "A", "B"]) == pytest.approx(1.0)
    # A judge that always says "A" against a balanced human set: 50% raw agreement,
    # but kappa near 0 because that agreement is pure chance.
    human = ["A", "B"] * 10
    always_a = ["A"] * 20
    assert abs(stats.cohens_kappa(always_a, human)) < 1e-9


def test_agreement_rate():
    assert stats.agreement_rate(["A", "A", "B"], ["A", "B", "B"]) == pytest.approx(2 / 3)


def test_kappa_ci_brackets_point_estimate():
    a = ["A", "B", "A", "B", "A", "A", "B", "B", "A", "B"]
    b = ["A", "B", "A", "A", "A", "A", "B", "B", "B", "B"]
    k = stats.cohens_kappa(a, b)
    lo, hi, se = stats.kappa_bootstrap_ci(a, b, n_boot=2000, seed=1)
    assert lo <= k <= hi
    assert se >= 0


def test_spearman_monotone():
    rho, p = stats.spearman([1, 2, 3, 4, 5], [2, 4, 6, 8, 10])
    assert rho == pytest.approx(1.0)


# ---- judge calling (fake backend) ----------------------------------------

def _canned(preferred, confidence=4):
    """A backend that always returns the same JSON verdict."""
    body_seen = {}
    def backend(body):
        body_seen["last"] = body
        return {"choices": [{"message": {"content": json.dumps(
            {"preferred": preferred, "confidence": confidence, "reasoning": "because"})}}]}
    backend.seen = body_seen
    return backend


def test_judge_pairwise_ab_frame():
    v = judge_pairwise("q", "aaa", "bbb", model="m", backend=_canned("A"), item_id="i1", order="AB")
    assert v.preferred == "A" and v.confidence == 4 and v.order == "AB"


def test_judge_pairwise_ba_folds_back_to_ab_frame():
    # In BA ordering the shown responses are swapped, so a raw "A" (the first shown,
    # which is original B) must fold back to original "B".
    v = judge_pairwise("q", "aaa", "bbb", model="m", backend=_canned("A"), item_id="i1", order="BA")
    assert v.preferred == "B"


def test_debiased_detects_inconsistency():
    # A backend that always prefers whichever response is shown SECOND has position bias.
    def second_pref(body):
        return {"choices": [{"message": {"content": json.dumps(
            {"preferred": "B", "confidence": 3, "reasoning": "x"})}}]}
    d = judge_pairwise_debiased("q", "aaa", "bbb", model="m", backend=second_pref, item_id="i")
    assert isinstance(d, DebiasedVerdict)
    # AB -> prefers B; BA -> raw B folds to A. Inconsistent -> tie.
    assert not d.consistent and d.final_preferred == "tie"


def test_parse_content_strips_code_fence():
    resp = {"choices": [{"message": {"content": "```json\n{\"preferred\": \"A\", \"confidence\": 5}\n```"}}]}
    assert parse_content(resp)["preferred"] == "A"


# ---- validation -----------------------------------------------------------

def test_validate_perfect_judge():
    human = ["A", "B", "A", "B", "A", "B"]
    rep = validate_judge(human, list(human), model="perfect")
    assert rep.agreement_rate == pytest.approx(1.0)
    assert rep.cohens_kappa == pytest.approx(1.0)
    assert rep.n_items == 6


def test_validate_position_bias_and_items_needed():
    human = ["A", "B"] * 8
    pref_ab = list(human)                       # agrees in AB ordering
    pref_ba = ["B", "A"] * 8                     # flips in BA ordering -> full position bias
    rep = validate_judge(human, pref_ab, pref_ba, model="biased")
    assert rep.position_bias_rate == pytest.approx(1.0)
    # every item became a 'tie' after debiasing, so no decisive items remain
    assert rep.n_items == 16


def test_validate_length_correlation():
    # Judge always prefers A; make A always the longer response -> positive length corr.
    human = ["A", "B", "A", "B", "A", "B"]
    pref = ["A"] * 6
    len_a = [100, 100, 100, 100, 100, 100]
    len_b = [10, 10, 10, 10, 10, 10]
    rep = validate_judge(human, pref, model="verbose", len_a=len_a, len_b=len_b)
    assert rep.length_correlation is None or rep.length_correlation >= 0  # A longer, A preferred


def test_panel_verdict_majority():
    from assay.judge import panel_verdict
    v = panel_verdict(["A", "A", "B", "A", "tie"])
    assert v["panel_preferred"] == "A"
    assert v["votes_a"] == 3 and v["votes_b"] == 1 and v["n_abstain"] == 1
    assert v["agreement"] == pytest.approx(3 / 4)
    assert not v["unanimous"]


def test_panel_verdict_unanimous_and_empty():
    from assay.judge import panel_verdict
    assert panel_verdict(["B", "B", "B"])["unanimous"] is True
    empty = panel_verdict(["tie", "tie"])
    assert empty["panel_preferred"] is None and empty["n_abstain"] == 2


def test_run_panel_aggregates():
    from assay.judge import run_panel
    # A content-aware backend that prefers whichever SHOWN response contains "WIN".
    # This stays order-consistent (folds to original A), so the panel is unanimous.
    def backend(body):
        user = body["messages"][1]["content"]
        shown_a = user.split("Response A:\n")[1].split("\n\nResponse B:")[0]
        pref = "A" if "WIN" in shown_a else "B"
        return {"choices": [{"message": {"content": json.dumps(
            {"preferred": pref, "confidence": 5, "reasoning": "x"})}}]}
    out = run_panel("q", "WIN here", "nope", models=["m1", "m2", "m3"], backend=backend)
    assert out["panel"]["panel_preferred"] == "A"
    assert out["panel"]["unanimous"] is True
    assert set(out["verdicts"]) == {"m1", "m2", "m3"}


def test_reconcile_judges():
    ids = ["i1", "i2", "i3", "i4"]
    ja = ["A", "A", "B", "B"]
    jb = ["A", "B", "B", "A"]
    out = reconcile_judges(ids, ja, jb, "ga", "gb")
    assert out["agreement_rate"] == pytest.approx(0.5)
    assert out["n_disagreements"] == 2
    assert 0.0 <= out["mcnemar_p"] <= 1.0
