"""Generate the illustrative example fixtures, deterministically.

IMPORTANT / HONESTY NOTE
------------------------
The files this script writes are *synthetic illustrative fixtures*. They use the
real on-disk *schema* of lm-eval samples and of frozen GSM8K generations, so the
adapters and the reconciler exercise the exact code path they would on real
data. They are NOT real model outputs and contain no real benchmark content.

Assay's actual audits run on real, public data (Open LLM Leaderboard per-sample
details, GSM8K-Platinum, MMLU-Redux, HELM logs). These fixtures exist only to
make `assay check` and `assay reconcile` runnable offline and to back the unit
tests. Nothing here should be reported as a finding.

Run:  python examples/make_fixtures.py
"""
from __future__ import annotations

import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


# --- GSM8K frozen generations ---------------------------------------------
# Each item: (gold, completion). Completions are written so that lm-eval's
# strict-match (needs the '#### N' delimiter) and flexible-extract (last number
# anywhere) diverge, reproducing the *direction* of the real strict/flexible gap.
GSM8K = [
    (18, "She collects 18 eggs and keeps them all. #### 18"),
    (3, "Each robe needs 2 bolts of blue and 1 of white, so 3 bolts. The answer is 3."),
    (6, "Half of the 12 cars are sold, leaving 6 cars. #### 6"),
    (5, "He reads 5 pages every night before bed. The final answer is 5."),
    (39, "The repairs cost 39 dollars in total. #### 39"),
    (8, "There are 8 people at the table. Answer: 8"),
    (9, "Adding the piles gives 9 marbles. #### 9"),
    (29, "Natalia sold clips to 29 friends. The answer is 29."),
    (33, "Altogether that is 33 books. #### 33"),
    (48, "So the total comes to 48. The answer is 48 dollars."),
    (10, "After giving some away he has 10 left. #### 10"),
    (7, "The remainder is 7, so the answer is 7."),
    (140, "The trip covers 140 miles in total. #### 140"),
    (70, "It takes 70 minutes to finish. The answer is 70."),
    (23, "She now owns 23 books on the shelf. #### 23"),
    # flexible gets fooled: a distractor number appears AFTER the delimited answer
    (25, "First she earned 25 dollars washing cars. #### 25 (solved in 3 steps)"),
    (12, "The three groups sum to 12. #### 12. Verified across 6 examples."),
    (2, "He has 2 apples remaining. The answer is 2."),
    (4, "The quotient works out to 4. #### 4"),
    (15, "That leaves 15 cookies in the jar. #### 15"),
    (11, "Combining both amounts, the answer is 11."),
    (500, "The deposit was 500 dollars. #### 500"),
    (64, "The floor needs 64 tiles. The answer is 64."),
    # genuinely wrong: neither scorer can save a wrong answer
    (20, "I think it works out to 17. #### 17"),
]


def write_gsm8k() -> str:
    path = os.path.join(HERE, "gsm8k_frozen.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for i, (gold, completion) in enumerate(GSM8K):
            fh.write(json.dumps({"id": f"g{i:03d}", "gold": gold, "completion": completion}) + "\n")
    return path


# --- lm-eval samples with a subject cluster key ---------------------------
# Six subjects; some near-all-correct, some near-all-wrong. That within-subject
# correlation is what makes the clustered SE exceed the naive SE, which is the
# whole point of the demo. 6 clusters (<30) also exercises the small-cluster
# warning + bootstrap cross-check path.
SUBJECTS = {
    "abstract_algebra": 1,   # 1 of 8 correct
    "anatomy": 8,            # 8 of 8
    "astronomy": 7,          # 7 of 8
    "college_chemistry": 1,  # 1 of 8
    "world_religions": 8,    # 8 of 8
    "virology": 2,           # 2 of 8  (echoes the MMLU-Redux Virology error cluster)
}
ITEMS_PER_SUBJECT = 8


def write_lm_eval() -> str:
    path = os.path.join(HERE, "sample_lm_eval.jsonl")
    doc_id = 0
    with open(path, "w", encoding="utf-8") as fh:
        for subject, n_correct in SUBJECTS.items():
            for j in range(ITEMS_PER_SUBJECT):
                acc = 1 if j < n_correct else 0
                obj = {
                    "doc_id": doc_id,
                    "doc": {
                        "subject": subject,
                        "question": f"MMLU-schema item {doc_id} (illustrative fixture, not real content)",
                    },
                    "target": "A",
                    "filtered_resps": ["A"],
                    "acc": acc,
                    "arguments": [[f"prompt::{subject}::{doc_id}", "A"]],
                }
                fh.write(json.dumps(obj) + "\n")
                doc_id += 1
    return path


# --- gate: two checkpoints over 200 shared items -------------------------
# Baseline ~70% accuracy; the candidate flips 10 items right and 6 wrong for a
# net +2.0 pts. That is a small gain over a 200-item eval, so the gate should
# read it as UNDERPOWERED (the delta is below the eval's noise floor).
N_GATE = 200
TASKS = [f"task{i}" for i in range(5)]


def _gate_scores(seed=17):
    rng = np.random.default_rng(seed)
    baseline = (rng.random(N_GATE) < 0.70)
    wrong = np.where(~baseline)[0]
    right = np.where(baseline)[0]
    rng.shuffle(wrong)
    rng.shuffle(right)
    candidate = baseline.copy()
    candidate[wrong[:10]] = True    # 10 genuine gains
    candidate[right[:6]] = False    # 6 genuine losses  -> net +4 items = +2.0 pts
    tasks = [TASKS[i % len(TASKS)] for i in range(N_GATE)]
    return baseline.astype(int), candidate.astype(int), tasks


def _write_checkpoint(path, scores, tasks):
    with open(path, "w", encoding="utf-8") as fh:
        for i, (acc, task) in enumerate(zip(scores, tasks)):
            fh.write(json.dumps({
                "doc_id": f"g{i:03d}",
                "doc": {"task": task, "question": f"item {i} (illustrative fixture)"},
                "acc": int(acc),
                "arguments": [[f"prompt::{i}", "A"]],
            }) + "\n")
    return path


def write_gate():
    base, cand, tasks = _gate_scores()
    p1 = _write_checkpoint(os.path.join(HERE, "gate_baseline.jsonl"), base, tasks)
    p2 = _write_checkpoint(os.path.join(HERE, "gate_candidate.jsonl"), cand, tasks)
    return p1, p2


# --- IRT: a (models x items) outcome matrix from known 2PL parameters -----
# Simulated from a known ground truth so the fitter can be validated by
# parameter recovery. The truth is saved alongside for the test suite.
def write_irt(seed=7, n_models=60, n_items=120):
    from assay import irt
    rng = np.random.default_rng(seed)
    theta = np.sort(rng.normal(0, 1, n_models))
    b = rng.normal(0, 1.2, n_items)
    a = np.exp(rng.normal(0.0, 0.4, n_items))  # lognormal discriminations in ~[0.5, 2]
    Y, _ = irt.simulate_2pl(theta, a, b, seed=seed)
    out = os.path.join(HERE, "irt_outcomes.jsonl")
    with open(out, "w", encoding="utf-8") as fh:
        for m in range(n_models):
            fh.write(json.dumps({"model": f"m{m:02d}", "scores": [int(x) for x in Y[m]]}) + "\n")
    truth = os.path.join(HERE, "irt_truth.json")
    json.dump({"theta": theta.tolist(), "a": a.tolist(), "b": b.tolist()}, open(truth, "w"))
    return out, truth


if __name__ == "__main__":
    for p in (write_gsm8k(), write_lm_eval(), *write_gate(), *write_irt()):
        print("wrote", p)
