"""Tune MiniCheck label bands on the hand-labelled claims.

  python -m evals.tune_minicheck            # writes evals/results/minicheck_thresholds.json

Scores every claim once (max support probability over the top-3 source chunks, per sentence), then
grid-searches t_high / t_low. Objective: fewest false SUPPORTED (a PARTIAL or UNSUPPORTED claim labelled
SUPPORTED), then best accuracy. 40 claims is a small set: treat the thresholds as a starting point.
"""
from __future__ import annotations

import json
import os
import time

from app import llm
from app.config import EVALS_DIR

OUT = EVALS_DIR / "results" / "minicheck_thresholds.json"


def score_all() -> tuple[list[dict], float]:
    os.environ["ROLE_CLAIM_CHECKER"] = "minicheck-flan-t5"
    from app.agents import claim_checker
    from app.services.reader import html_to_text
    spec = llm.resolve("claim_checker")
    data = json.loads((EVALS_DIR / "labeled" / "claims.json").read_text(encoding="utf-8"))["claims"]
    rows, t0 = [], time.time()
    for c in data:
        probs = claim_checker.minicheck_scores(spec, c["claim"], html_to_text(c["source_text"]))
        rows.append({"claim": c["claim"], "gold": c["label"], "probs": [round(p, 4) for p in probs]})
    return rows, (time.time() - t0) / max(1, len(rows))


def evaluate(rows: list[dict], t_high: float, t_low: float) -> dict:
    from app.agents.claim_checker import band, combine
    confusion: dict[str, int] = {}
    right = false_sup = 0
    for r in rows:
        got = combine([band(p, t_high, t_low) for p in r["probs"]])
        key = f"{r['gold']}->{got}"
        confusion[key] = confusion.get(key, 0) + 1
        right += got == r["gold"]
        false_sup += got == "SUPPORTED" and r["gold"] != "SUPPORTED"
    not_sup = sum(r["gold"] != "SUPPORTED" for r in rows)
    return {"t_high": t_high, "t_low": t_low, "accuracy": round(right / len(rows), 3), "false_supported": false_sup,
            "false_supported_rate": round(false_sup / not_sup, 3) if not_sup else 0.0,
            "confusion": dict(sorted(confusion.items()))}


def main() -> None:
    rows, per_claim_s = score_all()
    grid = [round(x / 100, 2) for x in range(2, 100)]
    results = [evaluate(rows, hi, lo) for hi in grid for lo in grid if lo < hi]
    best = min(results, key=lambda r: (r["false_supported"], -r["accuracy"], -r["t_high"], r["t_low"]))
    default = evaluate(rows, 0.9, 0.5)
    out = {"model": llm.resolve("claim_checker").model.name,
           "objective": "min false SUPPORTED, then max accuracy (ties: higher t_high, lower t_low)",
           "chosen": best, "untuned_default_0.9_0.5": default,
           "mean_seconds_per_claim": round(per_claim_s, 3), "claims": rows}
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "claims"}, indent=1))


if __name__ == "__main__":
    main()
