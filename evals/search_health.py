"""Search health: run Phase 1 for a brief and report how search, fetching and reading went.

  python -m evals.search_health evals/briefs/invoice_templates.json [more briefs ...] --out evals/results/search_baseline.json

Everything is read back from the run's own decision log and Evidence Ledger, so the numbers describe exactly
what the pipeline did (nothing is re-queried or re-scored here).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlparse

from app.models import FounderInput
from app.orchestrator import orchestrator as orch
from app.services import decision_log, ledger


def domain(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def health(brief_path: str) -> dict:
    data = json.loads(Path(brief_path).read_text(encoding="utf-8"))
    t0 = time.time()
    st = orch.start(FounderInput(**data.get("founder_input", data)), background=False)
    rid = st["id"]
    log = decision_log.read(rid)
    searches = [e for e in log if e["action"] == "web_search"]
    reads = [e for e in log if e["action"] == "read_page_isolated"]
    fails = [e for e in log if e["action"] in ("fetch_failed", "read_failed", "fetch_rejected")]
    responded = sorted({en for e in searches for en in e.get("engines", [])})
    unresponsive = sorted({f"{u[0]}: {u[1]}" for e in searches for u in e.get("unresponsive", [])})
    result_urls = [u for e in searches for u in e["sources"]]
    rec = st.get("gates", {}).get("desk_evidence", {})
    demand = next((c["value"] for c in rec.get("result", {}).get("checks", []) if c["name"] == "demand_signals"), None)
    counted = [c for c in ledger.all_claims(rid) if c.type == "demand_signal" and ledger.counts_for_gate(c)]
    return {
        "brief": Path(brief_path).stem, "run_id": rid, "status": st["status"], "seconds": round(time.time() - t0, 1),
        "verdict": rec.get("result", {}).get("verdict"),
        "queries": [{"query": e.get("query"), "results": len(e["sources"]), "origin": e.get("origin"),
                     "engines": e.get("engines", [])} for e in searches],
        "engines_responded": responded, "engines_unresponsive": unresponsive,
        "distinct_result_domains": len({domain(u) for u in result_urls}),
        "pages_read": len(reads),
        "pages_failed": [{"url": e["sources"][0] if e["sources"] else None, "reason": e.get("reason") or e.get("origin")}
                         for e in fails],
        "text_chars_per_page": {e["sources"][0]: e.get("text_chars") for e in reads if e["sources"]},
        "demand_signals_at_gate": demand,
        "demand_signal_domains": sorted({domain(c.source_url) for c in counted}),
        "demand_signal_sources": _by_source(counted),
        "community_posts": sum(1 for e in log if e["action"] == "community_post_added"),
        "demand_rejected_by_classifier": [{"url": (e["sources"] or [None])[0], "reason": e.get("reason")}
                                          for e in log if e["action"] == "demand_rejected"],
        "tavily_budget_fallbacks": sum(1 for e in log if e["action"] == "tavily_budget_fallback"),
    }


def _by_source(claims) -> dict:
    """Counted demand signals per source: the provider named in the claim note ('via ...'), else the domain."""
    import re
    out: dict = {}
    for c in claims:
        m = re.search(r"via ([\w ]+?)(?: API)?(?:$|[.;])", c.note or "")
        key = f"{m.group(1)} ({domain(c.source_url)})" if m else domain(c.source_url)
        out[key] = out.get(key, 0) + 1
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("briefs", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rows = [health(b) for b in a.briefs]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    for r in rows:
        print(f"{r['brief']}: {r['seconds']}s verdict={r['verdict']} queries={len(r['queries'])} "
              f"engines={len(r['engines_responded'])} unresponsive={len(r['engines_unresponsive'])} "
              f"domains={r['distinct_result_domains']} read={r['pages_read']} failed={len(r['pages_failed'])} "
              f"demand={r['demand_signals_at_gate']} from={r['demand_signal_sources']} community_posts={r['community_posts']} "
              f"classifier_rejects={len(r['demand_rejected_by_classifier'])}")


if __name__ == "__main__":
    main()
