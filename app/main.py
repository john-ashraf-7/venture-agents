"""FastAPI app: founder UI (server-rendered), progress streaming, Outbox approvals, kill switch,
local landing pages and MOCKED delivery downloads."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app import approval, gates, llm
from app.agents import base as agent_base
from app.agents import interview_analyst, rehearsal
from app.commerce import delivery, payments, refunds
from app.config import ROOT, data_dir, env, founder_mode, load_yaml, mocks, profile_name
from app.models import Brief, FounderInput, GuidePack, MemoBody, PricingSheet, Provenance, now_iso
from app.orchestrator import orchestrator as orch
from app.services import decision_log, events, guard, ledger, outbox
from app.services.storage import conn, kv_get

log = logging.getLogger("venture")
app = FastAPI(title="Venture Builder", version="0.1.0")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "ui" / "templates"))
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[a-z]{2,}$", re.I)


@app.on_event("startup")
def _startup() -> None:
    for w in llm.config_warnings():
        log.warning("CONFIG WARNING: %s", w)


# Local approval token: Outbox approvals must carry it, so a page on another site cannot approve anything.
# Set APPROVE_TOKEN to fix it; otherwise a new one is generated at startup and printed to the console.
APPROVE_TOKEN = env("APPROVE_TOKEN") or secrets.token_urlsafe(16)
logging.getLogger("uvicorn.error").warning("Outbox approval token for this session: %s", APPROVE_TOKEN)


def models_status() -> dict[str, Any]:
    """Which configured Ollama models are present yet (the UI starts while ollama-pull is still downloading)."""
    wanted = sorted({llm.model_name(r) for r in load_yaml("models.yaml")["roles"]
                     if llm.resolve(r).model.provider_kind == "ollama"})
    try:
        import httpx
        have = {m["name"] for m in httpx.get(f"{env('OLLAMA_URL', 'http://ollama:11434')}/api/tags", timeout=3).json().get("models", [])}
    except Exception:
        return {"ready": False, "missing": wanted, "note": "Ollama not reachable yet"}
    missing = [w for w in wanted if w not in have and f"{w}:latest" not in have]
    return {"ready": not missing, "missing": missing, "note": "models loading" if missing else "models ready"}


def _ctx(request: Request, **kw: Any) -> dict[str, Any]:
    return {"request": request, "profile": profile_name(), "mode": founder_mode(), "killed": events.KILL.is_set(),
            "mocks": mocks(), "warnings": llm.config_warnings(), "models": models_status(),
            "approve_token": APPROVE_TOKEN, **kw}


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "profile": profile_name(), "killed": events.KILL.is_set(), "time": now_iso(),
            "models": models_status()}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> Any:
    briefs = sorted((ROOT / "evals" / "briefs").glob("*.json"))
    examples = {p.stem: json.loads(p.read_text(encoding="utf-8"))["founder_input"] for p in briefs}
    return templates.TemplateResponse(request, "index.html", _ctx(request, runs=orch.list_runs()[:20], examples=examples))


@app.post("/runs")
def create_run(idea: str = Form(...), skills: str = Form(""), budget: str = Form(""), time: str = Form(""),
               target_market: str = Form(""), values: str = Form("")) -> Any:
    if events.KILL.is_set():
        raise HTTPException(409, "Kill switch is on. Release it first.")
    st = orch.start(FounderInput(idea=idea, skills=skills, budget=budget, time=time, target_market=target_market, values=values))
    return RedirectResponse(f"/runs/{st['id']}", status_code=303)


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_page(request: Request, run_id: str) -> Any:
    try:
        st = orch.load(run_id)
    except KeyError:
        raise HTTPException(404)
    claims = ledger.all_claims(run_id)
    metrics = ledger.metrics(claims)
    by_artifact: dict[str, Any] = {}
    for c in claims:
        by_artifact.setdefault(c.artifact_id or "-", []).append(c)
    artifact_metrics = {k: ledger.metrics(v) for k, v in by_artifact.items()}
    hypotheses = _hypotheses(run_id, claims)
    exp = orch.experiment_status(run_id).to_dict() if gates.get_lock(run_id, "experiment") else None
    return templates.TemplateResponse(request, "run.html", _ctx(
        request, st=st, claims=claims, metrics=metrics, artifact_metrics=artifact_metrics,
        spot=ledger.spot_check(claims), outbox=outbox.items(run_id), control=orch.founder_control(run_id),
        cost=orch.cost.summary(run_id), hypotheses=hypotheses, exp=exp, landing_served=kv_get(run_id, "landing_served", False),
        orders=kv_get(run_id, "orders", []), deliveries=kv_get(run_id, "deliveries", {}),
        shadow=kv_get(run_id, "shadow_support", []), awaiting=st.get("awaiting")))


def _hypotheses(run_id: str, claims: list) -> list[dict[str, Any]]:
    risk = (kv_get(run_id, "artifact:riskiest") or {}).get("items", [])
    out = []
    import re as _re
    for r in risk:
        words = set(_re.findall(r"\w{5,}", r["text"].lower()))
        rel = [c for c in claims if words & set(_re.findall(r"\w{5,}", c.text.lower()))]
        out.append({"text": r["text"], "risk": r["risk"],
                    "for": [c for c in rel if c.label.value == "SUPPORTED"],
                    "against_or_open": [c for c in rel if c.label.value != "SUPPORTED"]})
    return out


@app.get("/api/runs/{run_id}")
def run_json(run_id: str) -> Any:
    st = orch.load(run_id)
    st.pop("founder_input", None)
    return st


@app.get("/runs/{run_id}/events")
async def stream(run_id: str) -> StreamingResponse:
    async def gen():
        i = 0
        while True:
            new = events.since(run_id, i)
            for e in new:
                yield events.sse_format(e)
            i += len(new)
            await asyncio.sleep(0.4)
    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/runs/{run_id}/file/{name}")
def artifact_file(run_id: str, name: str) -> Any:
    if not re.match(r"^[\w.\-]+$", name):
        raise HTTPException(400)
    p = decision_log.run_dir(run_id) / name
    if not p.exists():
        raise HTTPException(404)
    if name.endswith(".html"):
        return HTMLResponse(p.read_text(encoding="utf-8"))
    return PlainTextResponse(p.read_text(encoding="utf-8"))


@app.post("/runs/{run_id}/gates/{gate}/decide")
def decide(run_id: str, gate: str, choice: str = Form(...), reason: str = Form(""), niche: str = Form("")) -> Any:
    try:
        orch.decide(run_id, gate, choice, reason, {"niche": niche})
    except approval.ApprovalError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


@app.post("/runs/{run_id}/gates/{gate}/reconsider")
def reconsider(run_id: str, gate: str, message: str = Form(...)) -> Any:
    return orch.reconsider(run_id, gate, message)


@app.post("/runs/{run_id}/ask")
def ask(run_id: str, request_text: str = Form(...)) -> Any:
    """Free-form founder request. Guarded on the way in and on the way out."""
    g = guard.check(request_text, run_id=run_id, context="founder_input")
    if not g.allowed:
        return {"refused": True, "message": guard.refusal_message(g), "layer": g.layer, "rules": g.rule_ids}
    brief = orch.artifact(run_id, "brief", Brief)
    out = agent_base.run(run_id, "copywriter", "copywriter", "founder_request_draft", MemoBody,
                         {"brief": brief, "request": request_text[:2000]},
                         instructions="Draft what the founder asked for. Never invent reviews, testimonials, numbers, "
                                      "urgency or income promises; label projections as ASSUMPTION scenarios.")
    g2 = guard.check(out.body, run_id=run_id, context="final_artifact:founder_request")
    if not g2.allowed:
        return {"refused": True, "message": guard.refusal_message(g2), "layer": g2.layer}
    return {"refused": False, "draft": out.body, "note": "Draft only. Nothing is published without Outbox approval."}


@app.post("/outbox/{item_id}/approve")
def approve(item_id: str, note: str = Form(""), token: str = Form("")) -> Any:
    if not secrets.compare_digest(token, APPROVE_TOKEN):
        raise HTTPException(403, "Missing or wrong approval token (shown in the UI and the app console).")
    try:
        it = outbox.approve(item_id, note)
    except outbox.OutboxRejected as e:
        raise HTTPException(400, str(e))
    return RedirectResponse(f"/runs/{it['run_id']}#outbox", status_code=303)


@app.post("/outbox/{item_id}/reject")
def reject(item_id: str, reason: str = Form("")) -> Any:
    it = outbox.reject(item_id, reason)
    return RedirectResponse(f"/runs/{it['run_id']}#outbox", status_code=303)


@app.post("/kill")
def kill() -> Any:
    orch.kill()
    return RedirectResponse("/", status_code=303)


@app.post("/unkill")
def unkill() -> Any:
    orch.unkill()
    return RedirectResponse("/", status_code=303)


@app.post("/runs/{run_id}/publish")
def publish(run_id: str) -> Any:
    return {"copied": orch.publish(run_id)}


# ----------------------------------------------------------------- landing page -----------
def _src(src: str) -> str:
    s = (src or "").strip().lower()
    if s in ("demo", "demo_audience", "judges", "live-demo"):
        return "demo_audience"
    if s in ("sim", "simulated"):
        return "simulated"
    return re.sub(r"[^\w-]", "", s)[:30] or "direct"


@app.get("/lp/{run_id}", response_class=HTMLResponse)
def landing(run_id: str, src: str = "") -> Any:
    if not kv_get(run_id, "landing_served", False):
        raise HTTPException(403, "This landing page is not served: it needs founder approval in the Outbox first.")
    with conn() as c:
        c.execute("INSERT INTO visits (run_id, ts, source) VALUES (?,?,?)", (run_id, now_iso(), _src(src)))
    return HTMLResponse((data_dir() / "landing" / f"{run_id}.html").read_text(encoding="utf-8"))


@app.post("/lp/{run_id}/signup", response_class=HTMLResponse)
def signup(run_id: str, email: str = Form(...), src: str = Form("")) -> Any:
    if not kv_get(run_id, "landing_served", False):
        raise HTTPException(403)
    if not EMAIL.match(email.strip()):
        raise HTTPException(400, "invalid email")
    with conn() as c:
        c.execute("INSERT INTO signups (run_id, email, ts, source) VALUES (?,?,?,?)", (run_id, email.strip().lower(), now_iso(), _src(src)))
    note = " (tagged demo_audience: never counted as evidence)" if _src(src) == "demo_audience" else ""
    return HTMLResponse(f"<p>Thanks - you're on the waitlist{note}. <a href='/lp/{run_id}/delete'>Delete my email</a></p>")


@app.get("/lp/{run_id}/delete", response_class=HTMLResponse)
def delete_form(run_id: str) -> Any:
    return HTMLResponse(f"<form method='post'><input type='email' name='email' required><button>Delete my email</button></form>")


@app.post("/lp/{run_id}/delete", response_class=HTMLResponse)
def delete_email(run_id: str, email: str = Form(...)) -> Any:
    with conn() as c:
        n = c.execute("DELETE FROM signups WHERE run_id=? AND email=?", (run_id, email.strip().lower())).rowcount
    return HTMLResponse(f"<p>Deleted {n} record(s).</p>")


# ----------------------------------------------------------------- sale to cash (MOCKED) --
@app.post("/runs/{run_id}/simulate_order")
def simulate_order(run_id: str) -> Any:
    sheet = orch.artifact(run_id, "pricing", PricingSheet)
    if not sheet:
        raise HTTPException(400, "No approved pricing yet.")
    o = payments.simulate_order_received(run_id, sheet.tiers[0].name, sheet.tiers[0].price_usd)
    d = delivery.deliver(run_id, o["order_id"])
    return {"label": "MOCKED", "order": o, "delivery": d}


@app.post("/runs/{run_id}/refund_request/{order_id}")
def refund_request(run_id: str, order_id: str, reason: str = Form("")) -> Any:
    return refunds.request_refund(run_id, order_id, reason)


@app.get("/download/{run_id}/{token}", response_class=HTMLResponse)
def download(run_id: str, token: str) -> Any:
    if not delivery.token_valid(run_id, token):
        raise HTTPException(403, "Access revoked or invalid (MOCKED delivery).")
    files = sorted((decision_log.run_dir(run_id)).glob("phase3_step3_product_guide*.html"))
    if not files:
        raise HTTPException(404)
    return HTMLResponse(files[-1].read_text(encoding="utf-8"))


# ----------------------------------------------------------------- Phase 2 extras ---------
@app.post("/runs/{run_id}/interview_notes")
def interview_notes(run_id: str, notes: str = Form(...)) -> Any:
    g = guard.check(notes, run_id=run_id, context="founder_input")
    if not g.allowed:
        return {"refused": True, "message": guard.refusal_message(g)}
    brief = orch.artifact(run_id, "brief", Brief)
    ins = interview_analyst.run(run_id, notes, brief.target_market if brief else "")
    orch.write(run_id, 2, "step5", "interview_insights", "# Interview insights (from founder-pasted notes)\n\n## Patterns\n\n"
               + "\n".join(f"- {p}" for p in ins.patterns) + "\n\n## Quotes\n\n" + "\n".join(f"> {q}" for q in ins.quotes)
               + "\n\n## Open questions\n\n" + "\n".join(f"- {q}" for q in ins.open_questions) + "\n")
    return ins.model_dump()


@app.post("/runs/{run_id}/rehearse")
def rehearse(run_id: str, persona: int = Form(0), question: str = Form(...)) -> Any:
    brief = orch.artifact(run_id, "brief", Brief)
    if not brief:
        raise HTTPException(400, "Run Phase 1 first.")
    return rehearsal.ask(run_id, brief, persona, question)


@app.post("/replay/{name}")
def replay(name: str) -> Any:
    if name not in ("signups_12_of_100", "signups_130_of_100", "insufficient_sample"):
        raise HTTPException(404)
    return orch.replay_fixture(name)


@app.post("/runs/{run_id}/experiment/recheck")
def recheck(run_id: str) -> Any:
    return orch.experiment_status(run_id).to_dict()


@app.post("/runs/{run_id}/shadow/signoff")
def shadow_signoff(run_id: str) -> Any:
    """Founder signs off shadow-mode support drafts; each still goes through the Outbox."""
    items = []
    for r in kv_get(run_id, "shadow_support", []):
        items.append(outbox.submit(run_id, "send_support_reply", title=f"Support reply to ticket {r['ticket_id']}",
                                   content=r["draft"], target=f"ticket {r['ticket_id']} (MOCKED inbox)",
                                   target_provenance=Provenance.founder, requested_by="support"))
    decision_log.append(run_id, "founder", "shadow_mode_signoff", approved_by="founder", initiated_by="founder")
    return RedirectResponse(f"/runs/{run_id}#outbox", status_code=303)
