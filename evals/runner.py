"""Eval harness.  make eval ROLE=<role> MODELS=a,b   (inside the app container)

  python -m evals.runner --role policy_guard --models qwen-8b,gpt-oss-safeguard-20b
  python -m evals.runner --role claim_checker --models qwen-8b,gpt-oss-20b
  python -m evals.runner --role desk_gate --profiles demo-fast,quality      # fixture search, all briefs

Writes a markdown results table to evals/results/<role>.md and prints it.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from app import llm
from app.config import EVALS_DIR
from app.models import CheckResult, FounderInput
from app.services import guard

OUT = EVALS_DIR / "results"


def eval_policy_guard(model_key: str) -> dict:
    os.environ["ROLE_POLICY_GUARD"] = model_key
    data = json.loads((EVALS_DIR / "labeled" / "prompts.json").read_text(encoding="utf-8"))
    t0 = time.time()
    missed = [p for p in data["trick"] if guard.check(p).allowed]
    fp = [p for p in data["benign"] if not guard.check(p).allowed]
    # layer-2-only: what the model decides when every prompt is sent to it
    l2_missed = 0
    from app.models import PolicyDecision
    from app.config import CONFIG_DIR
    policy = (CONFIG_DIR / "policy.md").read_text(encoding="utf-8")
    lat = []
    for p in data["trick"] + data["benign"]:
        s = time.time()
        try:
            d = llm.call("policy_guard", [{"role": "system", "content": policy}, {"role": "user", "content": "Text:\n" + p}], PolicyDecision)
            if p in data["trick"] and d.decision == "ALLOW":
                l2_missed += 1
        except llm.LLMError:
            l2_missed += 1 if p in data["trick"] else 0
        lat.append(time.time() - s)
    return {"model": model_key, "miss_rate_two_layer": len(missed) / len(data["trick"]),
            "false_positive_rate": len(fp) / len(data["benign"]), "miss_rate_model_only": l2_missed / len(data["trick"]),
            "mean_latency_s": round(sum(lat) / len(lat), 2), "wall_s": round(time.time() - t0, 1)}


def eval_claim_checker(model_key: str) -> dict:
    os.environ["ROLE_CLAIM_CHECKER"] = model_key
    from app.config import prompt
    from app.services.reader import html_to_text, wrap
    data = json.loads((EVALS_DIR / "labeled" / "claims.json").read_text(encoding="utf-8"))["claims"]
    right, lat = 0, []
    confusion: dict = {}
    for c in data:
        s = time.time()
        try:
            r = llm.call("claim_checker", [{"role": "system", "content": prompt("claim_checker")},
                                           {"role": "user", "content": f"CLAIM: {c['claim']}\nSOURCE URL: {c['source_url']}\n" + wrap(html_to_text(c['source_text']))}],
                         CheckResult, use_cache=False)
            got = r.label
        except llm.LLMError:
            got = "ERROR"
        lat.append(time.time() - s)
        confusion[f"{c['label']}->{got}"] = confusion.get(f"{c['label']}->{got}", 0) + 1
        right += got == c["label"]
    false_support = sum(v for k, v in confusion.items() if k.startswith("UNSUPPORTED->SUPPORTED"))
    return {"model": model_key, "accuracy": round(right / len(data), 3), "false_supported": false_support,
            "mean_latency_s": round(sum(lat) / len(lat), 2), "confusion": confusion}


def eval_desk_gate(profile: str) -> list[dict]:
    os.environ["PROFILE"] = profile
    os.environ.setdefault("SEARCH_MODE", "fixtures")
    from app.orchestrator import orchestrator as orch
    rows = []
    for p in sorted((EVALS_DIR / "briefs").glob("*.json")):
        b = json.loads(p.read_text(encoding="utf-8"))
        t0 = time.time()
        st = orch.start(FounderInput(**b["founder_input"]), background=False)
        got = "BLOCKED" if st["status"] == "blocked" else st.get("gates", {}).get("desk_evidence", {}).get("result", {}).get("verdict", st["status"])
        rows.append({"profile": profile, "brief": p.stem, "expected": "/".join(b["expected_outcomes"]), "got": got,
                     "ok": got in b["expected_outcomes"], "seconds": round(time.time() - t0, 1)})
    return rows


def table(rows: list[dict]) -> str:
    if not rows:
        return "(no rows)"
    keys = list(rows[0].keys())
    lines = ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
    lines += ["| " + " | ".join(str(r[k]) for k in keys) + " |" for r in rows]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", required=True, choices=["policy_guard", "claim_checker", "desk_gate"])
    ap.add_argument("--models", default="qwen-8b")
    ap.add_argument("--profiles", default="demo-fast,quality")
    a = ap.parse_args()
    if a.role == "policy_guard":
        rows = [eval_policy_guard(m) for m in a.models.split(",")]
    elif a.role == "claim_checker":
        rows = [eval_claim_checker(m) for m in a.models.split(",")]
    else:
        rows = [r for p in a.profiles.split(",") for r in eval_desk_gate(p)]
    OUT.mkdir(exist_ok=True)
    md = f"# Eval: {a.role}\n\n" + table(rows) + "\n"
    (OUT / f"{a.role}.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
