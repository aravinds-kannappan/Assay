import json, sys, re

OUT = "results/judge_pointwise/chunks/chunk_00.jsonl"
SCORE_KEYS = ["score", "rating", "helpfulness", "value"]

def extract_score(content):
    if content is None:
        return None, ""
    text = content.strip()
    # try direct JSON parse
    obj = None
    try:
        obj = json.loads(text)
    except Exception:
        # try to find a JSON object substring
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
            except Exception:
                obj = None
    score = None
    reasoning = ""
    if isinstance(obj, dict):
        for k in SCORE_KEYS:
            if k in obj and obj[k] is not None:
                try:
                    v = int(obj[k])
                    if 0 <= v <= 4:
                        score = v
                        break
                except (ValueError, TypeError):
                    pass
        r = obj.get("reasoning")
        if isinstance(r, str):
            reasoning = r
    elif isinstance(obj, (int, float)):
        v = int(obj)
        if 0 <= v <= 4:
            score = v
    else:
        # bare number in text
        m = re.fullmatch(r"\s*([0-4])\s*", text)
        if m:
            score = int(m.group(1))
    reasoning = (reasoning or "").strip()[:240]
    return score, reasoning

def main(path):
    data = json.load(open(path))
    iid = data["item_id"]
    hh = data["human_helpfulness"]
    rows = []
    for r in data["results"]:
        model = r["model"]
        content = r.get("content")
        score, reasoning = extract_score(content)
        rows.append({"item_id": iid, "model": model,
                     "human_helpfulness": hh, "score": score,
                     "reasoning": reasoning})
    with open(OUT, "a") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    parseable = sum(1 for r in rows if r["score"] is not None)
    print(f"{iid}: wrote {len(rows)} rows, {parseable} with 0-4 score")

if __name__ == "__main__":
    main(sys.argv[1])
